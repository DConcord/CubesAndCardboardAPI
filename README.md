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
