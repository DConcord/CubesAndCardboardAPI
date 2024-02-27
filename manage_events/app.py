import json
import boto3
from boto3.dynamodb.conditions import Key
import dateutil.parser as parser
from datetime import datetime #, timedelta
import uuid
import botocore

TABLE_NAME = 'game_events'
ALLOWED_ORIGINS = [
  "http://localhost:8080",
  "https://localhost:8080",
  "https://myapp.dissonantconcord.com",
]
S3_BUCKET = 'cdkstack-bucket83908e77-7tr0zgs93uwh'

def ddb_default(obj):
    if isinstance(obj, set):
        return list(obj)
    elif str(type(obj)) == "<class 'decimal.Decimal'>":
        return int(obj)
    else:
        print(type(obj))
    raise TypeError

def key_exists(bucket, key):
    s3 = boto3.client("s3")
    try:
        s3.head_object(Bucket=bucket, Key=key)
        print(f"Key: '{key}' found!")
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "404":
            print(f"Key: '{key}' does not exist!")
        else:
            print("Something else went wrong")
            raise

def process_bgg_id(bgg_id):
    s3 = boto3.client("s3")
    key = f"{bgg_id}.png"
    if not key_exists(S3_BUCKET, key):
       # send message to sqs
       print(f"Sending message to SQS: f'{bgg_id}#{S3_BUCKET}'")
       sqs = boto3.client("sqs")
       queue_url = "https://sqs.us-east-1.amazonaws.com/569879156317/bgg_picture_sqs_queue" #sqs.get_queue_url(QueueName="bgg_picture_sqs_queue")["QueueUrl"]
       sqs.send_message(QueueUrl=queue_url, MessageBody=f'{bgg_id}#{S3_BUCKET}')
       print(f"Message sent to SQS: f'{bgg_id}#{S3_BUCKET}'")

    # s3.download_file(S3_BUCKET, key, f"/tmp/{bgg_id}.png")
    # return f"/tmp/{bgg_id}.png"        

def lambda_handler(event, context):

  # try:
  #   origin = event['headers']["Origin"]
  #   print(origin)
  # except :
  #   print(json.dumps({"event": event}))
  #   raise

  # # if origin not in ALLOWED_ORIGINS:
  # #   return {
  # #     "statusCode": 403,
  # #     'headers': {
  # #       "Access-Control-Allow-Origin": "*"
  # #     },
  # #     "body": "Origin not allowed"
  # #   }

  method = event['requestContext']['httpMethod']
  resource = event['resource']

  match resource:
    case '/event':
      match method:
        case 'GET':
          pass

        # Create Event
        case 'POST':
          data = json.loads(event["body"])

          player_pool = [
            "Luke",
            "Eric",
            "Colten",
            "Frank",
            "Wynn",
            "Scott",
            "Tim",
            "Kevin",
            "Agustin",
            "Steve",
            "Brett",
            "Jake",
            "Garrett",
            "Robert",
          ]
                
          new_event = {
            "event_id": {"S": data['event_id'] if 'event_id' in data else str(uuid.uuid4())}, # temp: allow supplying event_id
            "event_type": {"S": data['event_type'] if 'event_type' in data else "GameKnight"},
            "date": {"S": data['date']},
            "host": {"S": data['host']},
            "format": {"S": data['format']},
            "game": {"S": data['game']},
            "registered": {"SS": data['registered'] if data['host'] in data['registered'] else data['registered'].append(data['host'])},
            "player_pool": {"SS": player_pool} # temp
          }
          if 'bgg_id' in data: new_event["bgg_id"] = {"N": str(data['bgg_id'])}
          if 'total_spots' in data:  new_event["total_spots"] = {"N": str(data['total_spots'])}

          process_bgg_id(data["bgg_id"])

          # date = parser.parse(text).date().isoformat()
          ddb = boto3.client('dynamodb', region_name='us-east-1')
          response = ddb.put_item(
            TableName=TABLE_NAME,
            Item={**new_event},
            # Fail if item.event_id already exists
            ConditionExpression='attribute_not_exists(event_id)',
          )
          print("Event Created")
          return {
            "statusCode": 201,
            'headers': {
              "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps({
              "result": "success",
              "new_event": new_event,
            }, indent=4)
          }
        
        # Modify Event
        case 'PUT':
          data = json.loads(event["body"])
                
          modified_event = {
            "event_id": {"S": data['event_id']},
            "event_type": {"S": data['event_type']},
            "date": {"S": data['date']},
            "host": {"S": data['host']},
            "format": {"S": data['format']},
            "game": {"S": data['game']},
            "registered": {"SS": data['registered']},
            "player_pool": {"SS": data['player_pool']},
          }
          if 'bgg_id' in data: modified_event["bgg_id"] = {"N": str(data['bgg_id'])}
          if 'total_spots' in data: modified_event["total_spots"] = {"N": str(data['total_spots'])}

          process_bgg_id(data["bgg_id"])

          # date = parser.parse(text).date().isoformat()
          ddb = boto3.client('dynamodb', region_name='us-east-1')
          response = ddb.put_item(
            TableName=TABLE_NAME,
            Item={**modified_event},
            # Fail if item.event_id already exists
            ConditionExpression='attribute_exists(event_id)',
          )
          print("Event Updated")
          return {
            "statusCode": 201,
            'headers': {
              "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps({
              "result": "success",
              "modified_event": modified_event,
            }, indent=4)
          }
         
        # Delete Event
        case 'DELETE':
          event_id = event["queryStringParameters"]["event_id"]

          ddb = boto3.resource('dynamodb', region_name='us-east-1')
          table = ddb.Table(TABLE_NAME)
          response = table.delete_item(
            Key={ 'event_id': event_id },
            ConditionExpression="attribute_exists (event_id)",
          )
          if response["ResponseMetadata"]["HTTPStatusCode"] == 200:
            return {
              "statusCode": 200,
              'headers': {
                "Access-Control-Allow-Origin": "*"
              },
              "body": json.dumps({
                "result": "success; event deleted"}, default=ddb_default),
            }

    case '/events':
      match method:
         
        #  Get Events
        case 'GET':
          current_date = datetime.now().date().isoformat()
          # date = parser.parse(text).date().isoformat()
          ddb = boto3.resource('dynamodb', region_name='us-east-1')
          table = ddb.Table(TABLE_NAME)
          response = table.query(
            TableName=TABLE_NAME,
            IndexName='EventTypeByDate',
            Select='ALL_ATTRIBUTES',
            KeyConditionExpression=(Key('event_type').eq('GameKnight') & Key('date').gte(current_date)),
          )

          if response["ResponseMetadata"]["HTTPStatusCode"] == 200:
            return {
              "statusCode": 200,
              'headers': {
                "Access-Control-Allow-Origin": "*"
              },
              "body": json.dumps(response["Items"], default=ddb_default),
            }
             
                  


  if method: return {
    "statusCode": 200,
    'headers': {
      "Access-Control-Allow-Origin": "*"
    },
    "body": json.dumps(event, indent=4),
  }

  # table.put_item(
  #   Item={
  #     'id': 1,
  #     'name': 'ABC',
  #     'salary': 20000
  #   },
  # )




  # match method:
  #   case 'GET':
  #     pass
  #   case 'POST':
  #     pass
  #   case 'PUT':
  #     pass
  #   case 'DELETE':
  #     pass