import json
import boto3
from boto3.dynamodb.conditions import Key
from boto3.dynamodb.conditions import Attr
import dateutil.parser as parser
from datetime import datetime #, timedelta
import uuid
import botocore
import time
import os

TABLE_NAME = os.environ['table_name'] # 'game_events'
S3_BUCKET = os.environ['s3_bucket'] #'cdkstack-bucket83908e77-7tr0zgs93uwh'
SQS_URL = os.environ['sqs_url']

ALLOWED_ORIGINS = [
  'http://localhost:8080',
  'https://eventsdev.dissonantconcord.com',
  'https://events.cubesandcardboard.net',
  'https://www.cubesandcardboard.net',
  'https://cubesandcardboard.net'
]
COGNITO_POOL_ID = 'us-east-1_Okkk4SAZX'
PULL_BGG_PIC = False


def lambda_handler(event, context):
  origin = '*'
  if event and 'headers' in event and event['headers'] and 'Origin' in event['headers'] and event['headers']['Origin']:
    origin = event['headers']['Origin']
  
    if origin not in ALLOWED_ORIGINS: 
      print(json.dumps(event))
      print(f"WARNING: origin '{origin}' not allowed")
      return {
        'statusCode': 401,
        'headers': {'Access-Control-Allow-Origin': 'https://events.cubesandcardboard.net'},
        'body': json.dumps({'message': 'CORS Failure'}),
      }
  
  try:
    auth_groups = event['requestContext']['authorizer']['claims']['cognito:groups'].split(',')
  except KeyError:
    auth_groups = []

  method = event['requestContext']['httpMethod']
  api_path = event['resource']

  match api_path:
    case '/event':
      match method:
        case 'GET':
          pass


        # Create Event
        case 'POST':
          if not authorize(auth_groups, ['admin']): 
            print(json.dumps({
              'message': 'Not authorized',
              'requestContext': event['requestContext']
            }))
            return {
              'statusCode': 401,
              'headers': {'Access-Control-Allow-Origin': origin},
              'body': json.dumps({'message': 'Not authorized'})
            }
          print('Create Event')
          data = json.loads(event['body'])
          response = createEvent(data)
          print('Event Created; Publish public events.json')
          updatePublicEventsJson()
          if PULL_BGG_PIC: waitForBggPic(data['bgg_id'])
          return {
            'statusCode': 201,
            'headers': {'Access-Control-Allow-Origin': origin},
            'body': json.dumps({'result': 'Event Created'})
          }
        
        # Modify Event
        case 'PUT':
          if not authorize(auth_groups, ['admin']): 
            print(json.dumps({
              'message': 'Not authorized',
              'requestContext': event['requestContext']
            }))
            return {
              'statusCode': 401,
              'headers': {'Access-Control-Allow-Origin': origin},
              'body': json.dumps({'message': 'Not authorized'})
            }
          print('Modify Event')
          data = json.loads(event['body'])
          response = modifyEvent(data)
          print('Event Modified; Publish public events.json')
          updatePublicEventsJson()
          if PULL_BGG_PIC: waitForBggPic(data['bgg_id'])
          return {
            'statusCode': 201,
            'headers': {'Access-Control-Allow-Origin': origin},
            'body': json.dumps({'result': 'Event Modified'})
          }
                   
        # Delete Event
        case 'DELETE':
          if not authorize(auth_groups, ['admin']): 
            print(json.dumps({
              'message': 'Not authorized',
              'requestContext': event['requestContext']
            }))
            return {
              'statusCode': 401,
              'headers': {'Access-Control-Allow-Origin': origin},
              'body': json.dumps({'message': 'Not authorized'})
            }
          print('Delete Event')
          event_id = event['queryStringParameters']['event_id']
          response = deleteEvent(event_id)
          print('Event Deleted; Publish public events.json')
          updatePublicEventsJson()
          return {
            'statusCode': 201,
            'headers': {'Access-Control-Allow-Origin': origin},
            'body': json.dumps({'result': 'Event Deleted'})
          }
    case '/event/rsvp':

      # Add RSVP
      match method:
        case 'POST':
          print('Add RSVP for Event')
          data = json.loads(event['body'])
          response = addRSVP(data['event_id'], data['name'])
          return {
            'statusCode': 201,
            'headers': {'Access-Control-Allow-Origin': origin},
            'body': json.dumps({'result': 'RSVP Added'})
          }
        
    case '/events':
      match method:        
         
        #  Get Events
        case 'GET':
          print('Get Events')
          events = getFutureEvents(as_json=True)
          # events = getAllEvents(as_json=True)
          return {
            'statusCode': 200,
            'headers': {'Access-Control-Allow-Origin': origin},
            'body': events,
          }

    case '/players':
      match method:        
         
        # Get Players
        case 'GET':
          print('Get Players')
          users = getAllUsersInAllGroups()
          user_dict = reduceUserAttrib(users)
          return {
            'statusCode': 200,
            'headers': {'Access-Control-Allow-Origin': origin},
            'body': json.dumps(user_dict, indent=2, default=ddb_default)
          }

  print('Unhandled Method or Path')
  return {
    'statusCode': 200, #204,
    'headers': {'Access-Control-Allow-Origin': origin},
    'body': json.dumps({'auth_groups': auth_groups, 'event': event}, indent=4),
  }
# def lambda_handler() 

# Process ddb result classes  
# when dumping to json string
def ddb_default(obj):
  if isinstance(obj, set):
    return list(obj)
  elif str(type(obj)) == "<class 'decimal.Decimal'>":
    return int(obj)
  if isinstance(obj, datetime):
    return obj.isoformat()
  else:
    print(type(obj))
    # return int(obj)
  # raise TypeError

# Confirm whether an object exists in an S3 bucket
def key_exists(bucket, key):
  s3 = boto3.client('s3')
  try:
    s3.head_object(Bucket=bucket, Key=key)
    print(f"Key: '{key}' found!")
    return True
  except botocore.exceptions.ClientError as e:
    if e.response['Error']['Code'] == '404':
      print(f"Key: '{key}' does not exist!")
      return False
    else:
      print('Something else went wrong')
      raise

def authorize(membership:list, filter_groups:list ):
  if not membership:
    return False
    raise Exception('Not Authorized')
  if not set(membership).intersection(set(filter_groups)):
    return False
    raise Exception('Not Authorized')
  return True
  

# Check whether bgg image has already been pulled and send 
# an SQS to trigger pulling/resizing/saving it if not
def process_bgg_id(bgg_id):
  s3 = boto3.client('s3')
  key = f'{bgg_id}.png'
  if not key_exists(S3_BUCKET, key):
    PULL_BGG_PIC = True
    # send message to sqs
    print(f"Sending message to SQS: f'{bgg_id}#{S3_BUCKET}'")
    sqs = boto3.client('sqs')
    # queue_url = 'https://sqs.us-east-1.amazonaws.com/569879156317/bgg_picture_sqs_queue'
    sqs.send_message(QueueUrl=SQS_URL, MessageBody=f'{bgg_id}#{S3_BUCKET}')
    print(f"Message sent to SQS: f'{bgg_id}#{S3_BUCKET}'")

def waitForBggPic(bgg_id):
   # wait for 5 seconds at most
  for i in range(15):
    if key_exists(S3_BUCKET, f'{bgg_id}.png'):
      return
    else:
      print(f"Waiting for {bgg_id}.png to be pulled...")
      time.sleep(.25)

def modifyEvent(eventDict, process_bgg_id_image=True):                
  modified_event = {
    'event_id': {'S': eventDict['event_id']},
    'event_type': {'S': eventDict['event_type']},
    'date': {'S': eventDict['date']},
    'host': {'S': eventDict['host']},
    'organizer': {'S': eventDict['organizer']} if 'organizer' in eventDict else {'S': ''},
    'format': {'S': eventDict['format']},
    'game': {'S': eventDict['game']},
    'registered': {'SS': eventDict['registered']},
    'player_pool': {'SS': eventDict['player_pool']},
  }
  modified_event['attending'] = modified_event['registered']
  if 'bgg_id' in eventDict: modified_event['bgg_id'] = {'N': str(eventDict['bgg_id'])}
  if 'total_spots' in eventDict: modified_event['total_spots'] = {'N': str(eventDict['total_spots'])}
  if 'tbd_pic' in eventDict: modified_event['tbd_pic'] = {'S': eventDict['tbd_pic']}
  if 'migrated' in eventDict: modified_event['migrated'] = {'BOOL': eventDict['migrated']}
  if 'not_attending' in eventDict: 
    modified_event['not_attending'] = {'SS': eventDict['not_attending']}
  else :
    modified_event['not_attending'] = {'SS': ['placeholder']}

  # Make sure 'placeholder' is in not_attending and registered sets (will be deduplicated)
  if 'placeholder' not in modified_event['not_attending']['SS']:
    modified_event['not_attending']['SS'].append('placeholder')
  if 'placeholder' not in modified_event['registered']['SS']:
    modified_event['registered']['SS'].append('placeholder')
  if 'placeholder' not in modified_event['attending']['SS']:
    modified_event['attending']['SS'].append('placeholder')

  if process_bgg_id_image and 'bgg_id' in eventDict and eventDict['bgg_id']:
    process_bgg_id(eventDict['bgg_id'])

  # date = parser.parse(text).date().isoformat()
  ddb = boto3.client('dynamodb', region_name='us-east-1')
  response = ddb.put_item(
    TableName=TABLE_NAME,
    Item={**modified_event},
    # Fail if item.event_id already exists
    ConditionExpression='attribute_exists(event_id)',
  )
  print('Event Updated')

  return response
## modifyEvent(eventDict)
  

def createEvent(eventDict, process_bgg_id_image=True):

  # TEMP until Cognito is populated
  player_pool = [
    'Luke',
    'Eric',
    'Colten',
    'Frank',
    'Wynn',
    'Scott',
    'Tim',
    'Kevin',
    'Agustin',
    'Steve',
    'Brett',
    'Jake',
    'Garrett',
    'Robert',
  ]
        
  new_event = {
    'event_id': {'S': eventDict['event_id'] if 'event_id' in eventDict else str(uuid.uuid4())}, # temp: allow supplying event_id
    'event_type': {'S': eventDict['event_type'] if 'event_type' in eventDict else 'GameKnight'},
    'date': {'S': eventDict['date']},
    'host': {'S': eventDict['host']},
    'organizer': {'S': eventDict['organizer']} if 'organizer' in eventDict else {'S': ''},
    'format': {'S': eventDict['format']},
    'game': {'S': eventDict['game']},
    'registered': {'SS': eventDict['registered']},
    'player_pool': {'SS': player_pool} # temp
  }
  new_event['attending'] = new_event['registered']
  if 'bgg_id' in eventDict: new_event['bgg_id'] = {'N': str(eventDict['bgg_id'])}
  if 'total_spots' in eventDict:  new_event['total_spots'] = {'N': str(eventDict['total_spots'])}
  if 'tbd_pic' in eventDict: new_event['tbd_pic'] = {'S': eventDict['tbd_pic']}
  if 'migrated' in eventDict: new_event['migrated'] = {'BOOL': eventDict['migrated']}
  if 'not_attending' in eventDict: 
    new_event['not_attending'] = {'SS': eventDict['not_attending']}
  else :
    new_event['not_attending'] = {'SS': ['placeholder']}

  # Make sure 'placeholder' is in not_attending and registered sets (will be deduplicated)
  if 'placeholder' not in new_event['not_attending']['SS']:
    new_event['not_attending']['SS'].append('placeholder')
  if 'placeholder' not in new_event['registered']['SS']:
    new_event['registered']['SS'].append('placeholder')
  if 'placeholder' not in new_event['attending']['SS']:
    new_event['attending']['SS'].append('placeholder')

  # Start processing download for new game image if necessary
  if process_bgg_id_image and 'bgg_id' in eventDict and eventDict['bgg_id']:
    process_bgg_id(eventDict['bgg_id'])

  ddb = boto3.client('dynamodb', region_name='us-east-1')
  response = ddb.put_item(
    TableName=TABLE_NAME,
    Item={**new_event},
    # Fail if item.event_id already exists
    ConditionExpression='attribute_not_exists(event_id)',
  )
  print('Event Created')

  return response
## def createEvent(eventDict) 


def deleteEvent(event_id):   
  ddb = boto3.resource('dynamodb', region_name='us-east-1')
  table = ddb.Table(TABLE_NAME)
  response = table.delete_item(
    Key={ 'event_id': event_id },
    ConditionExpression='attribute_exists (event_id)',
  )
  return response
## def deleteEvent(event_id)


def getFutureEvents(event_type='GameKnight', as_json=True):   
  # date = parser.parse(text).date().isoformat()
  current_date = datetime.now().date().isoformat()
  ddb = boto3.resource('dynamodb', region_name='us-east-1')
  table = ddb.Table(TABLE_NAME)
  response = table.query(
    TableName=TABLE_NAME,
    IndexName='EventTypeByDate',
    Select='ALL_ATTRIBUTES',
    KeyConditionExpression=(Key('event_type').eq(event_type) & Key('date').gte(current_date)),
  )
  for event in response['Items']:
    if 'placeholder' in event['not_attending']: event['not_attending'].remove('placeholder') 
    if 'placeholder' in event['registered']: event['registered'].remove('placeholder')
    if 'placeholder' in event['attending']: event['attending'].remove('placeholder')
  if as_json:
     return json.dumps(response['Items'], default=ddb_default)
  else:
    return response


def getAllEvents(event_type='GameKnight', as_json=True):   
  # date = parser.parse(text).date().isoformat()
  current_date = datetime.now().date().isoformat()
  ddb = boto3.resource('dynamodb', region_name='us-east-1')
  table = ddb.Table(TABLE_NAME)
  response = table.query(
    TableName=TABLE_NAME,
    IndexName='EventTypeByDate',
    Select='ALL_ATTRIBUTES',
    KeyConditionExpression=(Key('event_type').eq(event_type)),
  )
  for event in response['Items']:
    try:

      if 'not_attending' not in event: event['not_attending'] = set([])
      if 'attending' not in event: event['attending'] = event['registered']
      
      if 'not_attending' in event and 'placeholder' in event['not_attending']: event['not_attending'].remove('placeholder') 
      if 'attending' in event and 'placeholder' in event['attending']: event['attending'].remove('placeholder')
      if 'placeholder' in event['registered']: event['registered'].remove('placeholder')
    except:
      json.dumps(event, default=ddb_default)
      raise
  if as_json:
     return json.dumps(response['Items'], default=ddb_default)
  else:
    return response


def updatePublicEventsJson():
  future_events_json = getFutureEvents(event_type='GameKnight', as_json=True)
  s3 = boto3.client('s3')
  s3.put_object(
    Body=future_events_json,
    Bucket=S3_BUCKET,
    Key='events.json',
    ContentType='application/json',
    CacheControl='no-cache',
    # CacheControl='max-age=0, no-cache, no-store, must-revalidate',
  )
  print('events.json updated')


def updatePlayersGroupsJson():
  players_groups = reduceUserAttrib(getAllUsersInAllGroups())
  s3 = boto3.client('s3')
  s3.put_object(
    Body=json.dumps(players_groups, indent=2, default=ddb_default),
    Bucket=S3_BUCKET,
    Key='players_groups.json',
    ContentType='application/json',
    CacheControl='no-cache' #max-age=0, no-cache, no-store, must-revalidate',
    # Metadata={'Cache-Control': 'max-age=0, no-cache, no-store, must-revalidate'}
  )
  print('players_groups.json updated')


def addRSVP(event_id, user_id):
  ddb = boto3.resource('dynamodb', region_name='us-east-1')
  table = ddb.Table(TABLE_NAME)
  response = table.update_item(
    Key={ 'event_id': event_id },
    UpdateExpression='ADD attending :rsvp',
    ConditionExpression=Attr('event_id').exists(),
    ExpressionAttributeValues={
      ':rsvp': user_id
    }
  )
  return response
## updateRsvp(event_id, name, rsvp)
## updateRsvp('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'Luke', 'registered')
## updateRsvp('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'Luke', 'not_attending')
## updateRsvp('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'Luke', 'attending')
## updateRsvp('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'Luke



def listAllUsers():
  client = boto3.client('cognito-idp', region_name='us-east-1')
  response = client.list_users(
    UserPoolId=COGNITO_POOL_ID
  )
  return response
## getAllUsers()

def listAllGroups():
  client = boto3.client('cognito-idp', region_name='us-east-1')
  response = client.list_groups(
    UserPoolId=COGNITO_POOL_ID
  )
  return response

def listUsersInGroup(group_name):
  client = boto3.client('cognito-idp', region_name='us-east-1')
  response = client.list_users_in_group(
    UserPoolId=COGNITO_POOL_ID,
    GroupName=group_name
  )
  return response['Users']

def getAllUsersInAllGroups():
  users = listAllUsers()
  user_dict = {'Users': {user['Username']: {'groups': set([]), 'attrib': {}, **user} for user in users['Users']}, 'Groups': {}}
  groups = listAllGroups()
  for group in groups['Groups']:
    user_dict['Groups'][group['GroupName']] = []
    grp_users = listUsersInGroup(group['GroupName'])
    for user in grp_users:
      user_dict['Users'][user['Username']]['groups'].add(group['GroupName'])
      user_dict['Groups'][group['GroupName']].append(user['Username'])
  for user_id, user in user_dict['Users'].items():
    # user_dict['Users'][user_id]['groups'] = list(user_dict['Users'][user_id]['groups']) in user_dict['Users']:
    for attrib in user["Attributes"]:
      user_dict['Users'][user_id]['attrib'][attrib['Name']] = attrib['Value']
  return user_dict

def reduceUserAttrib(user_dict):
  users = {'Users': {}, 'Groups': user_dict['Groups']}
  for user_id, user in user_dict['Users'].items():
    try:
      users['Users'][user_id] = {
        'groups': user['groups'],
        'attrib': {
          'given_name': user['attrib']['given_name']
      } }
    except:
      print(json.dumps(user, indent=2, default=ddb_default))
      quit()
    # if 'family_name' in user['attrib']: 
    #   users['Users'][user_id]['attrib']['family_name'] = user['attrib']['family_name']
  return users


if __name__ == '__main__':
  ## Dev:
  # export s3_bucket=cdkstack-bucketdevff8a9acd-pine3ubqpres
  # export table_name=game_events_dev      
  # export sqs_url=https://sqs.us-east-1.amazonaws.com/569879156317/bgg_picture_sqs_queue_dev 

  ## Prod:
  # export s3_bucket=cdkstack-bucket83908e77-7tr0zgs93uwh
  # export table_name=game_events     
  # export sqs_url=https://sqs.us-east-1.amazonaws.com/569879156317/bgg_picture_sqs_queue
  
  updatePublicEventsJson()
  updatePlayersGroupsJson()

  # events = getFutureEvents(event_type='GameKnight', as_json=False)['Items']
  # for event in events:
  #   print(list(event['not_attending']).append('placeholder'))
  #   quit()
  # print(json.dumps(getFutureEvents(event_type='GameKnight', as_json=False)['Items'], indent=2, default=ddb_default))
  
  
  # user_dict = getAllUsersInAllGroups()
  # # print(json.dumps(user_dict, indent=2, default=ddb_default))
  # print(json.dumps(reduceUserAttrib(user_dict), indent=2, default=ddb_default))

  # match method:
  #   case 'GET':
  #     pass
  #   case 'POST':
  #     pass
  #   case 'PUT':
  #     pass
  #   case 'DELETE':
  #     pass