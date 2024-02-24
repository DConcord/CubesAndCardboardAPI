# How to deploy

<!-- ## push swagger.yaml to s3 bucket

```
aws s3 cp swagger.yaml s3://cp-sam-deploy-east1/
``` -->

<!-- ## sam package

```
sam package --template-file template.yaml --output-template-file output.yaml --s3-bucket cp-sam-deploy-east1
``` -->

## sam deploy

<!-- sam deploy --template-file output.yaml --stack-name BasicApiGateway --capabilities CAPABILITY_IAM --region us-east-1 -->

```
sam deploy --template-file template.yaml --stack-name BasicApiGateway --capabilities CAPABILITY_IAM --region us-east-1 --s3-bucket cp-sam-deploy-east1

sam delete --stack-name BasicApiGateway --region us-east-1
```
