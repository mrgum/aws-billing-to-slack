from collections import defaultdict
import boto3
import datetime
import json
import os
import requests
import sys
from urllib.parse import urlsplit
from collections import OrderedDict
import io
import pprint

role = os.environ.get('CA_ROLE')

searchterm = None
if 'ACCOUNT_NAME_SEARCH_TERM' in os.environ:
    searchterm = os.environ.get('ACCOUNT_NAME_SEARCH_TERM')
accountlist = None
if 'ACCOUNT_IDS' in os.environ:
    accountlist = os.environ.get('ACCOUNT_IDS')


icon = 'https://icons.iconarchive.com/icons/custom-icon-design/flatastic-11/256/Cash-icon.png'
pagesize = 5
n_days = 7
top_n_services = 6
today = datetime.datetime.today()
week_ago = today - datetime.timedelta(days=n_days)


def get_root_account():
    """
    find the root account for the organization we are in
    do not assume a role first
    """
    org = boto3.client('organizations').describe_organization()
    return org['Organization']['MasterAccountId']


def hook_service(hook_url) -> str:
    hook_host = urlsplit(hook_url).hostname
    if hook_host == 'hooks.slack.com':
        return "slack"
    elif hook_host == 'outlook.office.com':
        return "teams"
    else:
        return "text"

    # Leaving out the full block because Slack doesn't like it: '█'
sparks = ['▁', '▂', '▃', '▄', '▅', '▆', '▇']


def sparkline(datapoints) -> str:
    lower = min(datapoints)
    upper = max(datapoints)
    width = upper - lower
    n_sparks = len(sparks) - 1

    line = ""
    for dp in datapoints:
        scaled = 1 if width == 0 else (dp - lower) / width
        which_spark = int(scaled * n_sparks)
        line += (sparks[which_spark])

    return line

# import inspect

# def dump_args(func):
#     """Decorator to print function call details - parameters names and effective values.
#     """
#     def wrapper(*args, **kwargs):
#         func_args = inspect.signature(func).bind(*args, **kwargs).arguments
#         func_args_str =  ', '.join('{} = {!r}'.format(*item) for item in func_args.items())
#         print(f'{func.__module__}.{func.__qualname__} ( {func_args_str} )')
#         return func(*args, **kwargs)
#     return wrapper

# compare the last and last but one cost
# @dump_args


def delta(costs):
    if len(costs) < 2 or costs[-2] == 0:
        return ' ({:6s}%)'.format("--")
    else:
        return ' (%+6.2f' % (((costs[-1] - costs[-2])/costs[-2]) * 100.0) + '%)'


def ddf(cost):
    return '${:.2f}'.format(cost)


def report_summary_text(r):
    if r['account_name'] == 'Total':
        return("Total cost yesterday was {}\n".format(
            ddf(r['total_costs'][-1]))
        )
    else:
        return("Account {}({}) cost yesterday was {}\n".format(
            r['account_name'],
            r['account_id'],
            ddf(r['total_costs'][-1])
        ))


def format_slack(r):
    """
    return a text block for slack to be concatenated
    """
    if r['account_name'] == 'Total':
        text = "Total cost yesterday was {}\n".format(
            ddf(r['total_costs'][-1])
        )
    else:
        text = "Account {}({}) cost yesterday was {}\n".format(
            r['account_name'],
            r['account_id'],
            ddf(r['total_costs'][-1])
        )

    text += "```\n"
    for service_name, costs in r['most_expensive_yesterday']:
        text += "{:40s} {:7s} {:7s} {:10s}\n".format(service_name,
                                                     sparkline(costs),
                                                     ddf(costs[-1]),
                                                     delta(costs))

    text += "{:40s} {:7s} {:7s} {:10s}\n".format("Other",
                                                 sparkline(r['other_costs']),
                                                 ddf(r['other_costs'][-1]),
                                                 delta(r['other_costs']))

    text += "{:40s} {:7s} {:7s} {:10s}\n".format("Total",
                                                 sparkline(r['total_costs']),
                                                 ddf(r['total_costs'][-1]),
                                                 delta(r['total_costs'])
                                                 )
    text += "```\n"
    return(text)


def ftm_fact_value(c):
    return "{:7s} {:7s} {:10s}".format(
        sparkline(c),
        ddf(c[-1]),
        delta(c)
    )


def format_teams_mcsection(r):

    summary = report_summary_text(r)
    section = dict()
    section['markdown'] = 'true'
    section['activityTitle'] = f"![]({icon}){summary}"
    section['activitySubtitle'] = 'subtitle to follow'

    facts = list()
    fact = dict()

    for service_name, costs in r['most_expensive_yesterday']:
        facts.append({'name': service_name, 'value': ftm_fact_value(costs)})

    facts.append({'name': "Other", 'value': ftm_fact_value(r['other_costs'])})

    facts.append({'name': "Total", 'value': ftm_fact_value(r['total_costs'])})

    section['facts'] = facts

    return section


def format_teams_acbody(r):
    card_body = list()

    label = OrderedDict()
    label['type'] = 'TextBlock'
    label['wrap'] = "true"

    if r['account_name'] == 'Total':
        label['text'] = "Total cost yesterday was {}".format(
            ddf(r['total_costs'][-1])
        )
    else:
        label['text'] = "Account {}({}) cost yesterday was {}".format(
            r['account_name'], r['account_id'], ddf(r['total_costs'][-1]))
    card_body.append(label)

    columns = OrderedDict()
    columns['service'] = accolumn("Service")
    columns['last7d'] = accolumn("Last7d")
    columns['dollaryday'] = accolumn("$Yday")
    columns['delta'] = accolumn("delta")

    for service_name, costs in r['most_expensive_yesterday']:
        columns['service']['items'].append(service_name)
        columns['last7d']['items'].append(sparkline(costs))
        columns['dollaryday']['items'].append(ddf(costs[-1]))
        columns['delta']['items'].append(delta(costs))

    columns['service']['items'].append("Other")
    columns['last7d']['items'].append(sparkline(r['other_costs']))
    columns['dollaryday']['items'].append(ddf(r['other_costs'][-1]))
    columns['delta']['items'].append(delta(r['other_costs']))

    columns['service']['items'].append("TOTAL")
    columns['last7d']['items'].append(sparkline(r['total_costs']))
    columns['dollaryday']['items'].append(ddf(r['total_costs'][-1]))
    columns['delta']['items'].append(delta(r['total_costs']))

    # extras
    # buffer += line_fmt.format(service="Tax (Monthly)", last7d=sparkline(tax), dollaryday=tax[-1], delta=delta(tax))

    columnset = OrderedDict()
    columnset['type'] = 'ColumnSet'
    columnset['columns'] = list()

    for col in columns.values():
        wrap = False
        column = OrderedDict()
        column['type'] = 'Column'
        if col['heading'] == 'Service':
            column['width'] = '42'
            wrap = True
        elif col['heading'] == 'Last7d':
            column['width'] = '20'
        elif col['heading'] == '$Yday':
            column['width'] = '10'
        elif col['heading'] == 'delta':
            column['width'] = '13'
        else:
            raise('unknown column')
        if col['heading'] == '$Yday' or col['heading'] == 'delta':
            column['horizontalContentAlignment'] = "Right"
        column['items'] = list()
        column['items'].append(acheader(col['heading']))
        for value in col['items']:
            if col['heading'] == '$Yday':
                column['items'].append(acdata(value))
            elif col['heading'] == 'delta':
                column['items'].append(acdata(value))
            else:
                column['items'].append(acdata(value, wrap=wrap))
        columnset['columns'].append(column)
    card_body.append(columnset)
    return card_body


def acdata(text, wrap=False):
    return acitem(text, sep=True, wrap=wrap)


def acheader(text):
    return acitem(text, weight="Bolder")


def acitem(text, sep=None, weight=None, wrap=False):
    element = defaultdict()
    element['type'] = "TextBlock"
    element['height'] = 'stretch'
    element['spacing'] = 'Small'
    if sep:
        element['separator'] = "true"
    if weight:
        element['weight'] = str(weight)
    if wrap:
        element['wrap'] = "true"
    element['text'] = str(text)
    return element


def accolumn(str):
    col = defaultdict()
    col['heading'] = str
    col['items'] = list()
    return col


def include_account(account):
    if accountlist is not None:
        for account_id in accountlist.split('|'):
            if account_id == account('Id'):
                return True
    if searchterm is None:
        return True
    for term in searchterm.split('|'):
        if term in account['Name'] or term in account['Name'].lower():
            return True
    return False


def cost_report(account) -> dict:
    """
    get the cost explorer costs from organizations main account
    """

    account_list = account['Id'] if isinstance(
        account['Id'], (list, tuple)) else [account['Id']]

    ce = boto3.client('ce',
                      aws_access_key_id=account['AccessKeyId'],
                      aws_secret_access_key=account['SecretAccessKey'],
                      aws_session_token=account['SessionToken']
                      )
    query = {
        "TimePeriod": {
            "Start": week_ago.strftime('%Y-%m-%d'),
            "End": today.strftime('%Y-%m-%d'),
        },
        "Granularity": "DAILY",
        "Filter": {
            "And": [{
                "Dimensions": {
                    "Key": "LINKED_ACCOUNT",
                    "Values": account_list
                },
            }, {
                "Not": {
                    "Dimensions": {
                        "Key": "RECORD_TYPE",
                        "Values": [
                            "Credit",
                            "Refund",
                            "Upfront",
                            "Support",
                        ]
                    }
                }

            }]
        },
        "Metrics": ["UnblendedCost"],
        "GroupBy": [
            {
                "Type": "DIMENSION",
                "Key": "SERVICE",
            },
        ],
    }

    result = ce.get_cost_and_usage(**query)

    cost_per_day_by_service = defaultdict(list)

    # Build a map of service -> array of daily costs for the time frame
    for day in result['ResultsByTime']:
        for group in day['Groups']:
            key = group['Keys'][0]
            cost = float(group['Metrics']['UnblendedCost']['Amount'])
            cost_per_day_by_service[key].append(cost)

    # remove Tax as it is monthly
    tax = cost_per_day_by_service['Tax']
    del cost_per_day_by_service['Tax']

    # Sort the map by yesterday's cost
    most_expensive_yesterday = sorted(
        cost_per_day_by_service.items(), key=lambda i: i[1][-1], reverse=True)

    other_costs = [0.0] * n_days
    for service_name, costs in most_expensive_yesterday[top_n_services:]:
        for i, cost in enumerate(costs):
            other_costs[i] += cost

    total_costs = [0.0] * n_days
    for day_number in range(n_days):
        for service_name, costs in most_expensive_yesterday:
            try:
                total_costs[day_number] += costs[day_number]
            except IndexError:
                total_costs[day_number] += 0.0

    r = dict()
    # clash of variable naming what does pep say
    r['account_id'] = account['Id']
    r['account_name'] = account['Name']
    r['most_expensive_yesterday'] = most_expensive_yesterday[:top_n_services]
    r['other_costs'] = other_costs
    r['tax'] = tax
    r['total_costs'] = total_costs

    return r


def report_cost(context, event):

    if 'CA_ACCOUNT' in os.environ:
        acct = os.environ.get('CA_ACCOUNT')
    else:
        acct = get_root_account()

    sts_connection = boto3.client('sts')
    acct_b = sts_connection.assume_role(
        RoleArn="arn:aws:iam::{}:role/{}".format(acct, role),
        RoleSessionName="cross_acct_lambda"
    )

    ACCESS_KEY = acct_b['Credentials']['AccessKeyId']
    SECRET_KEY = acct_b['Credentials']['SecretAccessKey']
    SESSION_TOKEN = acct_b['Credentials']['SessionToken']

    org = boto3.client('organizations',
                       aws_access_key_id=ACCESS_KEY,
                       aws_secret_access_key=SECRET_KEY,
                       aws_session_token=SESSION_TOKEN)

    response = org.list_accounts(MaxResults=pagesize)

    reports = []
    while True:
        for account in response['Accounts']:
            if include_account(account):
                # print('{Id} {Name}'.format(**account))
                account = {**account, **acct_b['Credentials']}
                reports.append(cost_report(account))

        if 'NextToken' not in response:
            break

        response = org.list_accounts(
            MaxResults=pagesize, NextToken=response['NextToken'])

    all_accounts = acct_b['Credentials']
    all_accounts['Id'] = list(map(lambda r: r['account_id'], reports))
    all_accounts['Name'] = 'Total'
    total_report = cost_report(all_accounts)
    reports.append(total_report)

    # summary is used by multiple report types
    summary = "Total cost yesterday was {}\n".format(
        ddf(total_report['total_costs'][-1]))

    """
    workout which format to use based on webhook
    """
    hook_urls = os.environ.get(
        'WEBHOOK_URLS') if 'WEBHOOK_URLS' in os.environ else 'https://example.com'

    for hook_url in hook_urls.split('|'):

        hook_type = hook_service(hook_url)

        if hook_type == 'slack':
            """
            slack version
            gather summaries and text, post as message
            """

            message = ""
            for report in reports:
                message += format_slack(report)

            resp = requests.post(
                hook_url,
                json={
                    "text": summary + "\n\n\n" + message + "\n",
                }
            )
            if resp.status_code == requests.codes.ok:
                print('posted {}'.format(summary))
            else:
                print("Warn HTTP %s: %s" % (resp.status_code, resp.text))

        elif hook_type == 'teams':
            """
            teams version
            get a list of text blocks and columnsets and make them the body of a adaptive card
            make the card an attachment
            add the attachment to a message
            such a faff
            """
            card = OrderedDict()
            card['@type'] = "MessageCard"
            card['@context'] = "http://schema.org/extensions"
            card['themeColor'] = "0076D7"
            card['summary'] = summary
            card['sections'] = list()

            for report in reports:
                card['sections'].append(format_teams_mcsection(report))

            output = io.StringIO(json.dumps(card, indent=4, sort_keys=False))
            headers = {"Content-Type": "application/json"}
            # resp = requests.post(
            #     'https://outlook.office.com/webhook/876f4e9a-3dc6-4cfa-8b54-23a12eb00908@5567eafd-e777-42a5-91bb-9440fd43b893/IncomingWebhook/90003bcf64fd44969343e6fae92a9d4a/9845b659-eb52-432c-9c8c-1dc2ac21145f',
            #     data=output,
            #     headers=headers,
            # )
            print(json.dumps(card, indent=4, sort_keys=False))
        else:
            print('new hook format')
            print(summary)


if __name__ == "__main__":
    if 'CA_ROLE' not in os.environ:
        raise "at the moment we need CA_ROLE set"
    report_cost(1, 1)
