# Install Dependencies

AWS SAM CLI

```
brew install aws-sam-cli
```

<!-- ## push swagger.yaml to s3 bucket

```
aws s3 cp swagger.yaml s3://cp-sam-deploy-east1/
``` -->

Install esbuild globally

```
npm install -g esbuild
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
sam build --config-env dev && sam deploy --config-env dev && date
```

## Prod

```
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
