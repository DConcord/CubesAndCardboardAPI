# How to deploy

<!-- ## push swagger.yaml to s3 bucket

```
aws s3 cp swagger.yaml s3://cp-sam-deploy-east1/
``` -->

## sam package

<!-- ```
sam package --template-file template.yaml --output-template-file output.yaml --s3-bucket cp-sam-deploy-east1
``` -->

## sam deploy

<!-- sam deploy --template-file output.yaml --stack-name GameKnightsEventsAPI --capabilities CAPABILITY_IAM --region us-east-1 -->

<!-- ```
sam build

sam deploy --template-file template.yaml --stack-name GameKnightsEventsAPI --capabilities CAPABILITY_IAM --region us-east-1 --s3-bucket cp-sam-deploy-east1 \
--confirm-changeset

sam delete --stack-name GameKnightsEventsAPI --region us-east-1
``` -->

<!-- sam build && sam deploy -->

sam build --config-env prod && sam deploy --config-env prod --confirm-changeset

sam build --config-env dev && sam deploy --config-env dev --confirm-changeset
