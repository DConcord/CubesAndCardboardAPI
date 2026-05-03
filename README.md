# Install Dependencies

AWS SAM CLI

```
brew install aws-sam-cli
```

<!-- ## push swagger.yaml to s3 bucket

```
aws s3 cp swagger.yaml s3://cp-sam-deploy-east1/
``` -->

Install esbuild in the root of the project folder

```
npm install
```

<!-- ## sam package -->

<!-- ```
sam package --template-file template.yaml --output-template-file output.yaml --s3-bucket cp-sam-deploy-east1
``` -->

# Deploy

Environment-specific parameters (dev vs prod) are defined in samconfig.yaml and passed to the SAM template for deployment. Use the "--config-env" prameter to specify dev vs prod during build/deploy

<!-- sam deploy --template-file output.yaml --stack-name GameKnightsEventsAPI --capabilities CAPABILITY_IAM --region us-east-1 -->

<!-- ```
sam build

sam deploy --template-file template.yaml --stack-name GameKnightsEventsAPI --capabilities CAPABILITY_IAM --region us-east-1 --s3-bucket cp-sam-deploy-east1 \
--confirm-changeset

sam delete --stack-name GameKnightsEventsAPI --region us-east-1
``` -->

<!-- sam build && sam deploy -->

## Sandbox

```
aws s3 cp ./rsvp_alerts_ts/template.html s3://sandbox-cubes-and-cardboard-backend
sam build --config-env sandbox && sam deploy --config-env sandbox && date
```

## Dev

```
aws s3 cp ./rsvp_alerts_ts/template.html s3://dev-cubes-and-cardboard-backend && \
sam build --config-env dev && sam deploy --config-env dev && date
```

## Prod

```
aws s3 cp ./rsvp_alerts_ts/template.html s3://prod-cubes-and-cardboard-backend && \
sam build --config-env prod && sam deploy --config-env prod && date
```

```
--confirm-changeset
```

# Test Locally

## Python

Initialize the python virtual env (venv) in the root folder of the project:

```
mkdir .venv
pipenv install
```

Initialize the venv (if not done so already by VSCode) and run the script

```
pipenv shell
python ./manage_events/app.py
```

## Node.JS

Initialize and Retrieve Node modules _<strong>in the JS Lambda folder</strong>_. For Example:

```
cd ./rsvp_alerts_ts
npm install
```

Export environment variables locally. Dev or example:

```
export RSVP_SQS_URL=X
export S3_BUCKET=cdkstack-bucketdevff8a9acd-pine3ubqpres
export TABLE_NAME=game_events_dev
```

Build the code in JS (can't run TS directly, it wraps JS) with SAM in the project root and run with node

```
cd ..
sam build --config-env dev
node .aws-sam/build/RsvpAlertsFunction/app.js
```

## Initial deployment: Bootstrap DB and S3 files:

NOTE: replace "sandbox" with appropriate environment

### Pre-deploy: SSM parameters (one-time, before first `sam deploy`)

BGG API token — global, not per-environment:

```
aws ssm put-parameter \
  --name "/cubesandcardboard/bgg/api-token" \
  --value "YOUR_BGG_TOKEN" \
  --type SecureString \
  --region us-east-1
```

To rotate an existing token, add `--overwrite`.

Ops alert email — global, not per-environment (used by CloudWatch Alarms SNS and OpsDigest Lambda):

```
aws ssm put-parameter \
  --name "/cubesandcardboard/ops/alert-email" \
  --value "your@email.com" \
  --type String \
  --region us-east-1
```

**After first prod deploy:** AWS sends a "Confirm subscription" email to the alert address for the SNS topic. Click the link before alarms can deliver.

### Post-deploy: Bootstrap DB and S3

```
aws lambda invoke \
  --region us-east-1 \
  --function-name manage_events_sandbox \
  --cli-binary-format raw-in-base64-out \
  --payload '{ "action": "initBootstrap" }' -

aws s3 cp ./rsvp_alerts_ts/template.html s3://sandbox-cubes-and-cardboard-backend

aws lambda invoke \
  --region us-east-1 \
  --function-name manage_events_sandbox \
  --cli-binary-format raw-in-base64-out \
  --payload '{ "action": "updatePrevSubEvents" }' -
```
