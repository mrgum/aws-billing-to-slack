# AWS Billing to Slack

![image](https://user-images.githubusercontent.com/261584/66362145-3903a200-e947-11e9-91bd-6e40e5919ac4.png)

Sends daily breakdowns of AWS costs to a Slack channel.

This version is written to run under Organizations and requires a role in the master/root account.

As the sharing of credits is more complicated in organisations, that feature has been removed for now.

# Install

1. Install [`serverless`](https://serverless.com/), which I use to configure the AWS Lambda function that runs daily.

    ```
    npm install -g serverless
    npm install
    ```

1. Create an [incoming webhook](https://www.slack.com/apps/new/A0F7XDUAZ) that will post to the channel of your choice on your Slack workspace. Grab the URL for use in the next step.

1. Create IAM policies in the master/root account to allow listing accounts and reading cost explorer access.

1. Create a IAM role in the master/root account with those roles and trust the account that you are running from to use it.

1. Deploy the system into your AWS account, replacing the webhook URL below with the one you generated above.

    ```
    serverless deploy --aws_profile=profilename --aws_region=eu-west-1 --slack_url="https://hooks.slack.com/services/xxx/yyy/zzzz" --ca_account=123456789012 --ca_role=Billing-and-Costs --account_name_search_term=service
    ```

    You can also run it once to verify that it works:

    ```
    serverless invoke --function report_cost
    ```

## Support for AWS Credits

If you have AWS credits on your account and want to see them taken into account on this report, head to [your billing dashboard](https://console.aws.amazon.com/billing/home?#/credits) and note down the "Expiration Date", "Amount Remaining", and the "as of" date towards the bottom of the page. Add all three of these items to the command line when executing the `deploy` or `invoke`:

    ```
    serverless deploy \
        --hook_urls="https://hooks.slack.com/services/xxx/yyy/zzzz|/outlook.office.com/webhook/uuid@uuid/IncomingWebhook/integer/uuid" \
        --credits_expire_date="mm/dd/yyyy" \
        --credits_remaining_date="mm/dd/yyyy" \
        --credits_remaining="xxx.xx"
    ```

## TODO

make this optional, not sure how to do that as the serverless.yml will need to change depending on what mode it runs in.

describe-organization can list the id of the master account of the invoking account but that might not be the one we want
