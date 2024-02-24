import json


def lambda_handler(event, context):

    return {
        "statusCode": 200,
        'headers': {
            "Access-Control-Allow-Origin": "*"
        },
        "body": json.dumps(event, indent=4),
        # "body": json.dumps({
        #     "message": "hello world",
        # }),
    }
