import json
import boto3
from boto3.dynamodb.conditions import Key
from boto3.dynamodb.conditions import Attr
from dateutil.relativedelta import relativedelta, SU
from datetime import datetime, timedelta, timezone 
from zoneinfo import ZoneInfo
import uuid
import botocore
import time
import os
import csv
from copy import deepcopy
class env:
  TABLE_NAME_PROD = os.environ['table_name_prod']
  TABLE_NAME = os.environ['table_name'] # 'game_events'
  S3_BUCKET = os.environ['s3_bucket'] #'cdkstack-bucket83908e77-7tr0zgs93uwh'
  RSVP_SQS_URL = os.environ['rsvp_sqs_url']
  SNS_TOPIC_ARN = os.environ['sns_topic']
  BACKEND_BUCKET = os.environ['backend_bucket']
  MODE = os.environ['mode']
  BGG_PICTURE_FN = os.environ['bgg_picture_fn']

  ALLOWED_ORIGINS = [
    'http://localhost:8080',
    'https://events.dev.dissonantconcord.com',
    'https://eventsdev.dissonantconcord.com',
    'https://events.cubesandcardboard.net',
    'https://www.cubesandcardboard.net',
    'https://cubesandcardboard.net',
    'https://sandbox-events.dissonantconcord.com',
  ]
  COGNITO_POOL_ID = os.environ['user_pool_id']
  COGNITO_POOL_ID_PROD = os.environ['user_pool_id_prod']
  COGNITO_CLOUDWATCH_ROLE = os.environ['cognito_cloudwatch_role']

pull_bgg_pic = False

class CsvTextBuilder(object):
  def __init__(self):
    self.csv_string = []

  def write(self, row):
    self.csv_string.append(row)
  
  @property
  def encoded_csv(self):
    return ''.join(self.csv_string).encode('utf-8')
  
  def encoded_csv_generator(self):
    yield ''.join(self.csv_string).encode('utf-8')



def lambda_handler(apiEvent, context):
  global pull_bgg_pic
  
  origin = '*'
  # if apiEvent and 'headers' in apiEvent and apiEvent['headers'] and 'Origin' in apiEvent['headers'] and apiEvent['headers']['Origin']:
  if apiEvent.get('headers') and  (apiEvent['headers'].get('Origin') or apiEvent['headers'].get('Sec-Fetch-Site')=='same-origin' ):
    if apiEvent['headers'].get('Origin'):
      origin = apiEvent['headers']['Origin']
    
      if origin not in env.ALLOWED_ORIGINS: 
        print(json.dumps(apiEvent, default=ddb_default))
        print(f"WARNING: origin '{origin}' not allowed")
        return {
          'statusCode': 401,
          'headers': {'Access-Control-Allow-Origin': 'https://events.cubesandcardboard.net'},
          'body': json.dumps({'message': 'CORS Failure'}),
        }
  elif apiEvent:    
    match apiEvent.get('action'):
      case 'updatePrevSubEvents':
        print('apiEvent.action: updatePrevSubEvents')
        print(json.dumps(apiEvent, default=ddb_default))
        return {
          'statusCode': 200, 
          'body': json.dumps(updatePrevSubEvents(), default=ddb_default)
        }
      
      case 'getContext':
        try:
          print( json.dumps(vars(context), default=ddb_default))
          return {'statusCode': 200, 'body': json.dumps(vars(context), default=ddb_default)}
        except Exception as e:
          return {'statusCode': 500, 'body': json.dumps(str(e))}
      
      case 'ProcessAllReservedSchedules':
        print('Process Refresh schedules for all upcoming Reserved Events')
        print(json.dumps(apiEvent, default=ddb_default))
        upcomingEvents = getEvents(dateGte=datetime.now(ZoneInfo("America/Denver")).isoformat()[:19])
        print(json.dumps({"upcomingEvents": [{'event_id': event['event_id'], 'format': event['format'], 'date': event['date']}  for event in upcomingEvents]}, default=ddb_default))
        for event in upcomingEvents:
          if event['format'] == 'Reserved':
            process_reserved_event_scheduled_tasks(reserved_event=event, action='create', target_arn=context.invoked_function_arn)
        return {'statusCode': 200, 'body': 'OK'}

      case 'updatePlayerPools':
        time.sleep(1)
        print('apiEvent.action: Update Player Pools')
        print(json.dumps(apiEvent, default=ddb_default))
        updatePlayerPools()
        print('Publish public events.json')
        updatePublicEventsJson()
        return {'statusCode': 200, 'body': 'OK'}
      
      case 'initBootstrap':
        print('apiEvent.action: initBootstrap')
        print(json.dumps(apiEvent, default=ddb_default))
        init_bootstrap()
        return {'statusCode': 200, 'body': 'OK'}
      
      # default
      case _:
        if apiEvent.get('action'):
          print(f'WARNING: Unexpected action {apiEvent.get('action')}')
          print(json.dumps(apiEvent, default=ddb_default))
          return {
            'statusCode': 401,
            'headers': {'Access-Control-Allow-Origin': 'https://events.cubesandcardboard.net'},
            'body': json.dumps({'message': f'Unexpected action: {apiEvent.get('action')}'}),
          }
    
    print('Unexpected Event (1)')
    print(json.dumps(apiEvent, default=ddb_default))
    return {
      'statusCode': 401,
      'headers': {'Access-Control-Allow-Origin': 'https://events.cubesandcardboard.net'},
      'body': json.dumps({'message': 'Unexpected Event (1)'})#, 'event': apiEvent}, default=ddb_default),
    }
  else:
    print('Unexpected Event (2)')
    print(json.dumps(apiEvent, default=ddb_default))
    return {
      'statusCode': 401,
      'headers': {'Access-Control-Allow-Origin': 'https://events.cubesandcardboard.net'},
      'body': json.dumps({'message': 'Unexpected Event (2)'})#, 'event': apiEvent}, default=ddb_default),
    }


  unauthorized = {
    'statusCode': 401,
    'headers': {'Access-Control-Allow-Origin': origin},
    'body': json.dumps({'message': 'Not authorized'})
  }
  
  try:
    auth_groups = apiEvent['requestContext']['authorizer']['claims']['cognito:groups'].split(',')
  except KeyError:
    auth_groups = []

  try:
    auth_sub = apiEvent['requestContext']['authorizer']['claims']['sub']
  except KeyError:
    auth_sub = None

  method = apiEvent['requestContext']['httpMethod']
  api_path = apiEvent['resource']

  match api_path:
    case '/event':
      match method:
        case 'GET':
          pass


        # Create Event
        case 'POST':
          print('Create Event')
          if not authorize(apiEvent, auth_groups, ['admin']):
            print('Not authorized. User is not admin')
            return unauthorized
          data = json.loads(apiEvent['body'])
          if len(data['date']) <= 19:
            data['date'] = datetime.fromisoformat(data['date']).replace(tzinfo=ZoneInfo('America/Denver')).isoformat()            
          response = createEvent(data)
          print(json.dumps({
            'log_type': 'event',
            'auth_sub': auth_sub,
            'auth_type': 'admin',
            'event_id': response['event_id'],
            'date': data['date'],
            'new': json.dumps(data, default=ddb_default),
            'action': 'create',
          }, default=ddb_default))
          
          print('Update Player Pools')
          updatePlayerPools()
          print('Event Created; Publish public events.json')
          updatePublicEventsJson()
          print(f'pull_bgg_pic = {pull_bgg_pic}')
          try:
            if pull_bgg_pic: waitForBggPic(data['bgg_id'])
          except Exception as e:
              print(e)
          if data['format'] == 'Reserved':
            data['event_id'] = response['event_id']
            process_reserved_event_scheduled_tasks(reserved_event=data, action='create', target_arn=context.invoked_function_arn)
          return {
            'statusCode': 201,
            'headers': {'Access-Control-Allow-Origin': origin},
            'body': json.dumps({'result': 'Event Created'})
          }
        
        # Modify Event
        case 'PUT':
          if not authorize(apiEvent, auth_groups, ['admin'], log_if_false=False): 
            print('Check for Event Host')
            data = json.loads(apiEvent['body'])
            event = getEvent(data['event_id'])
            if event['host'] != auth_sub:
              print(f"WARNING: user_id '{event['host']}' is not an admin or the event host. not authorized")
              return unauthorized
            diff = compareAttributes(event, data)
            host_modifiable = {'game', 'bgg_id', 'player_pool', 'attending', 'not_attending', 'finalScore'}
            event_updates = { k: data[k] for k in host_modifiable.intersection(set({**diff['added'], **diff['modified']}))}
            for key in  diff['removed']:
              if key not in event_updates and key in host_modifiable:
                event_updates[key] = ''
            if event_updates == {}:
              return {
                'statusCode': 204,
                'headers': {'Access-Control-Allow-Origin': origin}
              }
            if 'bgg_id' in event_updates and event_updates['bgg_id'] > 0 :
              process_bgg_id(event_updates['bgg_id'])
            try:
              updateEvent(data['event_id'], event_updates)
            except Exception as e:
              print(json.dumps({'ERROR': str(e), 'event_id': data['event_id'], 'event_updates': event_updates}))
              print(e)
              return {
                'statusCode': 500,
                'headers': {'Access-Control-Allow-Origin': origin},
                'body': json.dumps({'message': 'Internal Server Error'})
              }
            original = {k: event[k] for k in event_updates if k in event}
            print(json.dumps({
              'log_type': 'event',
              'auth_sub': auth_sub,
              'auth_type': 'host',
              'event_id': data['event_id'],
              'date': data['date'],
              'previous': json.dumps(original, default=ddb_default),
              'new': json.dumps(event_updates, default=ddb_default),
              'action': 'update',
            }, default=ddb_default))
            all_rsvp = set()
            no_change = set()
            for rsvp in ['attending', 'not_attending']:
              if rsvp in original:
                all_rsvp = all_rsvp.union(original[rsvp])
              if rsvp in event_updates:
                all_rsvp = all_rsvp.union(event_updates[rsvp])
              if rsvp in original and rsvp in event_updates:
                no_change = no_change.union(original[rsvp].intersection(event_updates[rsvp]))
            
            if all_rsvp:
              rsvp_change = all_rsvp - no_change
              changes = {}
              for player in rsvp_change:
                if 'attending' in original and player in original['attending']:
                  if 'not_attending' in event_updates and player in event_updates['not_attending']:
                    changes[player] = {'rsvp': 'not_attending', 'action': 'update'}
                  else:
                    changes[player] = {'rsvp': 'attending', 'action': 'delete'}
                elif 'not_attending' in original and player in original['not_attending']:
                  if 'attending' in event_updates and player in event_updates['attending']:
                    changes[player] = {'rsvp': 'attending', 'action': 'update'}
                  else:
                    changes[player] = {'rsvp': 'not_attending', 'action': 'delete'}
                elif 'attending' in event_updates and player in event_updates['attending']:
                    changes[player] = {'rsvp': 'attending', 'action': 'add'}
                elif 'not_attending' in event_updates and player in event_updates['not_attending']:
                    changes[player] = {'rsvp': 'not_attending', 'action': 'add'}
              for i, (player, rsvp) in enumerate(changes.items()):
                if i == 0:
                  process_rsvp_alert_task()   
                rsvp_dict = {
                  'log_type': 'rsvp',
                  'auth_sub': auth_sub,
                  'auth_type': 'host',
                  'event_id': data['event_id'],
                  'date': event['date'],
                  'user_id': player,
                  'action': rsvp['action'],
                  'rsvp': rsvp['rsvp'],
                }
                print(json.dumps(rsvp_dict))
                send_rsvp_sqs(rsvp_dict)
          
            print('Update Player Pools')
            updatePlayerPools()
            print('Event Modified; Publish public events.json')
            updatePublicEventsJson()
            print(f'pull_bgg_pic = {pull_bgg_pic}')
            try:
              if pull_bgg_pic: waitForBggPic(data['bgg_id'])
            except Exception as e:
                print(e)
            return {
              'statusCode': 201,
              'headers': {'Access-Control-Allow-Origin': origin},
              'body': json.dumps({'result': 'Event Modified'})
            }
          
          print('Modify Event')
          data = json.loads(apiEvent['body'])
          current_event = getEvent(data['event_id'])
          if len(data['date']) <= 19:
            data['date'] = datetime.fromisoformat(data['date']).replace(tzinfo=ZoneInfo('America/Denver')).isoformat()
          # Check if event format has changed to/from 'Reserved' or if reserved event date has changed
          if (
            'Reserved' in [current_event['format'], data['format']]  
            and (current_event['format'] != data['format'] or current_event['date'] != data['date'])
          ):
            if current_event['format'] != data['format']:
              if current_event['format'] == 'Reserved':
                # Delete the scheduled task for the no-longer reserved event
                _action = 'delete'
              else:
                # Create a new scheduled task for the newly reserved event
                _action = 'create'
            else:
              # Update the scheduled task for the existing event's new date
              _action = 'update'
            process_reserved_event_scheduled_tasks(reserved_event=data, action=_action, target_arn=context.invoked_function_arn)
          response = modifyEvent(data)
          diff = compareAttributes(current_event, data)
          event_prev = {**diff['removed'], **diff['previous']}
          event_new = {**diff['added'], **diff['modified']}
          print(json.dumps({
            'log_type': 'event',
            'auth_sub': auth_sub,
            'auth_type': 'admin',
            'event_id': data['event_id'],
            'date': current_event['date'],
            # 'previous': event_prev,
            # 'new': event_new,
            'previous': json.dumps(event_prev, default=ddb_default),
            'new': json.dumps(event_new, default=ddb_default),
            'new_final': data,
            'action': 'modify',
          }, default=ddb_default))
          all_rsvp = set()
          no_change = set()
          for rsvp in ['attending', 'not_attending']:
            if rsvp in event_prev:
              all_rsvp = all_rsvp.union(set(event_prev[rsvp]))
            if rsvp in event_new:
              all_rsvp = all_rsvp.union(set(event_new[rsvp]))
            if rsvp in event_prev and rsvp in event_new:
              no_change = no_change.union(set(event_prev[rsvp]).intersection(set(event_new[rsvp])))
          
          if all_rsvp:
            rsvp_change = all_rsvp - no_change
            changes = {}
            for player in rsvp_change:
              if 'attending' in event_prev and player in event_prev['attending']:
                if 'not_attending' in event_new and player in event_new['not_attending']:
                  changes[player] = {'rsvp': 'not_attending', 'action': 'update'}
                else:
                  changes[player] = {'rsvp': 'attending', 'action': 'delete'}
              elif 'not_attending' in event_prev and player in event_prev['not_attending']:
                if 'attending' in event_new and player in event_new['attending']:
                  changes[player] = {'rsvp': 'attending', 'action': 'update'}
                else:
                  changes[player] = {'rsvp': 'not_attending', 'action': 'delete'}
              elif 'attending' in event_new and player in event_new['attending']:
                  changes[player] = {'rsvp': 'attending', 'action': 'add'}
              elif 'not_attending' in event_new and player in event_new['not_attending']:
                  changes[player] = {'rsvp': 'not_attending', 'action': 'add'}
            for i, (player, rsvp) in enumerate(changes.items()):
              if i == 0:
                process_rsvp_alert_task()              
              rsvp_dict= {
                'log_type': 'rsvp',
                'auth_sub': auth_sub,
                'auth_type': 'admin',
                'event_id': data['event_id'],
                'date': current_event['date'],
                'user_id': player,
                'action': rsvp['action'],
                'rsvp': rsvp['rsvp'],
              }
              print(json.dumps(rsvp_dict))
              send_rsvp_sqs(rsvp_dict)

          print('Update Player Pools')
          updatePlayerPools()
          print('Event Modified; Publish public events.json')
          updatePublicEventsJson()
          print(f'pull_bgg_pic = {pull_bgg_pic}')
          try:
            if pull_bgg_pic: waitForBggPic(data['bgg_id'])
          except Exception as e:
              print(e)
          return {
            'statusCode': 201,
            'headers': {'Access-Control-Allow-Origin': origin},
            'body': json.dumps({'result': 'Event Modified'})
          }
                   
        # Delete Event
        case 'DELETE':
          print('Delete Event')
          if not authorize(apiEvent, auth_groups, ['admin']): 
            print(f"WARNING: user_id '{auth_sub}' is not an admin. not authorized")
            return unauthorized
          
          event_id = apiEvent['queryStringParameters']['event_id'] 
          current_event = getEvent(event_id)
          response = deleteEvent(event_id)
          print(json.dumps({
            'log_type': 'event',
            'auth_sub': auth_sub,
            'auth_type': 'admin',
            'event_id': event_id,
            'date': current_event['date'],
            'previous': json.dumps(current_event, default=ddb_default),
            'action': 'delete',
          }, default=ddb_default))
          print('Update Player Pools')
          updatePlayerPools()
          print('Event Deleted; Publish public events.json')
          updatePublicEventsJson()
          if current_event['format'] == 'Reserved':
            process_reserved_event_scheduled_tasks(reserved_event=current_event, action='delete', target_arn=context.invoked_function_arn)
          return {
            'statusCode': 201,
            'headers': {'Access-Control-Allow-Origin': origin},
            'body': json.dumps({'result': 'Event Deleted'})
          }
        
    # Players update their own RSVP to an event
    case '/event/rsvp':
      rsvp_change = {
        'attending': 'not_attending',
        'not_attending': 'attending'
      }
      # Add RSVP
      match method:
        case 'POST':
          print('Update RSVP for Event')
          data = json.loads(apiEvent['body'])
          if auth_sub != data['user_id']:
            print(f"WARNING: user_id '{data['user_id']}' does not match auth_sub '{auth_sub}'. not authorized")
            return unauthorized
          current_event = getEvent(data['event_id'], attributes=['date', 'attending', 'not_attending'])
          response = updateRSVP(data['event_id'], data['user_id'], data['rsvp'])
          if  data['user_id'] in current_event[rsvp_change[data['rsvp']]]:
            action = 'update'
          else:
            action = 'add'
          rsvp_dict = {
            'log_type': 'rsvp',
            'auth_sub': auth_sub,
            'auth_type': 'self',
            'event_id': data['event_id'],
            'date': current_event['date'],
            'user_id': data['user_id'],
            'action': action,
            'rsvp': data['rsvp'],
          }
          print(json.dumps(rsvp_dict))
          send_rsvp_sqs(rsvp_dict)
          process_rsvp_alert_task()
          print('Update Player Pools')
          updatePlayerPools()
          print('Publish public events.json')
          updatePublicEventsJson()
          return {
            'statusCode': 201,
            'headers': {'Access-Control-Allow-Origin': origin},
            'body': json.dumps({'result': 'RSVP Added'})
          }
        
      # Delete RSVP
      match method:
        case 'DELETE':
          print('Delete RSVP for Event')
          data = apiEvent['queryStringParameters']
          if auth_sub != data['user_id']:
            print(f"WARNING: user_id '{data['user_id']}' does not match auth_sub '{auth_sub}'. not authorized")
            return unauthorized
          current_event = getEvent(data['event_id'], attributes=['date'])
          response = deleteRSVP(data['event_id'], data['user_id'], data['rsvp'])
          rsvp_dict = {
            'log_type': 'rsvp',
            'auth_sub': auth_sub,
            'auth_type': 'self',
            'event_id': data['event_id'],
            'date': current_event['date'],
            'user_id': data['user_id'],
            'action': 'delete',
            'rsvp': data['rsvp'],
          }
          print(json.dumps(rsvp_dict))
          send_rsvp_sqs(rsvp_dict)
          process_rsvp_alert_task()
          print('Update Player Pools')
          updatePlayerPools()
          print('Event Deleted; Publish public events.json')
          updatePublicEventsJson()
          return {
            'statusCode': 201,
            'headers': {'Access-Control-Allow-Origin': origin},
            'body': json.dumps({'result': 'RSVP Removed'})
          }
        
    case '/events':
      match method:        
         
        #  Get Events
        case 'GET':
          print('Get Events')
          data = apiEvent['queryStringParameters']
          if data and 'dateGte' in data and data['dateGte']:
            if data['dateGte'] == 'all':
              dateGte = None # ALL
            else:
              dateGte = data['dateGte']
          else:
            # dateGte = None # ALL
            dateGte = datetime.now(ZoneInfo('America/Denver')).date() - timedelta(days=14)
          
          if data and 'dateLte' in data and data['dateLte']:
            if data['dateLte'] == '14d':
              dateLte = datetime.now(ZoneInfo('America/Denver')).date() - timedelta(days=14)
            elif data['dateLte'] == 'today':
              dateLte = datetime.now(ZoneInfo('America/Denver')).date()
            else:
              dateLte = data['dateLte']
          else:
            dateLte = None
          
          tableType = data.get('tableType', env.MODE) if data else env.MODE
          events = getEvents(dateGte = dateGte, dateLte = dateLte, tableType = tableType)

          # If not an admin, filter out 'private' events of which the member is not in the player pool
          if not authorize(apiEvent, auth_groups, ['admin'], log_if_false=False):
            events = [event for event in events if not (event['format'] == 'Private' and auth_sub not in event['player_pool'])]
          return {
            'statusCode': 200,
            'headers': {'Access-Control-Allow-Origin': origin},
            'body': json.dumps(events, default=ddb_default),
          }

    case '/players':
      match method:        
         
        # Get Players
        case 'GET':
          if authorize(apiEvent, auth_groups, ['admin'], log_if_false=False): 
            print('Get Players (admin)')
            refresh = 'no'
            params = apiEvent.get('queryStringParameters', {})
            if params.get('refresh'):
              refresh = params.get('refresh').lower()

            if refresh.lower() == 'yes':
              if params.get('user_pool'):
                user_pool=params.get('user_pool')
                print(f'Get {user_pool} players/groups')
                user_dict = getAllUsersInAllGroups(user_pool=user_pool)
              else:
                print('Get full players/groups refresh')
                user_dict = updatePlayersGroupsJson()
            else:
              user_dict = getJsonS3(env.BACKEND_BUCKET, 'players_groups.json')
          
          # Non-admin users just retrieve the public facing (reduced details) players_groups.json
          else:
            print('Get Players (non-admin)')
            user_dict = getJsonS3(env.S3_BUCKET, 'players_groups.json')
            
          return {
            'statusCode': 200,
            'headers': {'Access-Control-Allow-Origin': origin},
            'body': json.dumps(user_dict, indent=2, default=ddb_default)
          }
        
    case '/players/import':
      match method:        
         
        # Import Players
        case 'POST':
          print('Import Players')
          if not authorize(apiEvent, auth_groups, ['admin']): 
            print(f"WARNING: user_id '{auth_sub}' is not an admin. not authorized")
            return unauthorized
          
          data = json.loads(apiEvent['body'])
          import_players_groups = [info for user_id, info in getAllUsersInAllGroups(user_pool='prod')['Users'].items() if user_id in data]
          
          cognito = boto3.client('cognito-idp')
          r = cognito.get_csv_header(UserPoolId=env.COGNITO_POOL_ID)
          csv_headers = r['CSVHeader']
          import_csv = [
            {
              **{key: '' for key in csv_headers},
              **{
                'cognito:username': f"{player['attrib']['given_name']}@dissonantconcord.com".lower(),
                'cognito:mfa_enabled': 'FALSE',
                'email_verified': 'TRUE',
                'phone_number_verified': 'FALSE',
                'given_name': player['attrib']['given_name'],
                'family_name': player['attrib']['family_name'],
                'email': f"{player['attrib']['given_name']}@dissonantconcord.com".lower(),
                'custom:prev_sub': player['attrib']['sub']
              }
            } for player in import_players_groups
          ]
          csvfile = CsvTextBuilder()
          fieldnames = csv_headers
          writer = csv.DictWriter(csvfile, fieldnames)
          writer.writeheader()
          writer.writerows(import_csv)
          
          r = cognito.create_user_import_job(
            JobName=f'{env.MODE}_import', #datetime.now(ZoneInfo("America/Denver")).isoformat(), #[:19]
            UserPoolId=env.COGNITO_POOL_ID,
            CloudWatchLogsRoleArn=env.COGNITO_CLOUDWATCH_ROLE
          )
          import_job = r['UserImportJob']

          import urllib.request

          file_data = csvfile.encoded_csv
          file_name = "players_import.csv"

          # Create the request
          req = urllib.request.Request(import_job['PreSignedUrl'], data=file_data, method='PUT')
          req.add_header('Content-Disposition', f'attachment; filename="{file_name}"')
          req.add_header('x-amz-server-side-encryption', 'aws:kms')

          # Send the request and get the response
          try:
              with urllib.request.urlopen(req) as response:
                  http_response = response.read()
                  print(f"Upload successful. Status code: {response.getcode()}")
          except urllib.error.URLError as e:
              print(f"Upload failed. Error: {e.reason}")
              if hasattr(e, 'read'):
                  print(f"Error details: {e.read().decode('utf-8')}")

          r = cognito.start_user_import_job(
            UserPoolId=env.COGNITO_POOL_ID,
            JobId=import_job['JobId']
          )

          while r['UserImportJob']['Status'] in ['Created','Pending','InProgress']:
            time.sleep(1)
            r = cognito.describe_user_import_job(
              UserPoolId=env.COGNITO_POOL_ID,
              JobId=import_job['JobId']
            )
          
          users_dict = getAllUsersInAllGroups()
          user_prev_sub_dict = {user['attrib']['custom:prev_sub']: user['attrib']['sub'] for user in users_dict['Users'].values() if 'custom:prev_sub' in user['attrib']}

          for prev_user in import_players_groups:
            prev_sub = prev_user['attrib']['sub']
            new_sub = user_prev_sub_dict[prev_sub]
            
            for group in prev_user['groups']:
              response = cognito.admin_add_user_to_group(
                  UserPoolId=env.COGNITO_POOL_ID,
                  Username=new_sub,
                  GroupName=group
              )
          users_dict = updatePlayersGroupsJson()
          
          return {
            'statusCode': 200,
            'headers': {'Access-Control-Allow-Origin': origin},
            'body': json.dumps(users_dict, indent=2, default=ddb_default)
          }

    case '/player':
      match method:
        
        # Create new Player
        case 'POST':
          print('Create Player')
          if (
            not authorize(apiEvent, auth_groups, ['admin']) 
            or (env.MODE not in ['prod', 'sandbox'] and auth_sub != '34f8c488-0061-70bb-a6bd-ca58ce273d9c') # only allow colten in dev/test (or any admin in prod/sandbox)
          ):            
            print(f"WARNING: user_id '{auth_sub}' is not authorized to create players")
            return unauthorized
          
          data = json.loads(apiEvent['body'])
          attributes = [{'Name': attribute,'Value': value} for attribute, value in data.items() if attribute != 'groups']
          attributes.append({'Name': 'email_verified', 'Value': 'true'})
          client = boto3.client('cognito-idp')
          response = client.admin_create_user(
            UserPoolId=env.COGNITO_POOL_ID,
            Username=data['email'],
            UserAttributes=attributes,
            MessageAction='SUPPRESS'
          )
          # print(json.dumps(response, default=ddb_default))

          user_dict = getJsonS3(env.BACKEND_BUCKET, 'players_groups.json')
          user = response['User']
          user_id = user['Username']
          user_dict['Users'][user_id] = {'groups': [], 'attrib': {}, **user}
          for attrib in user['Attributes']:
            user_dict['Users'][user_id]['attrib'][attrib['Name']] = attrib['Value']
          for group in data['groups']:
            user_dict['Groups'][group].append(user_id)
            user_dict['Users'][user_id]['groups'].append(group)
            response = client.admin_add_user_to_group(
                UserPoolId=env.COGNITO_POOL_ID,
                Username=user_id,
                GroupName=group
            )
          print(json.dumps({
            'log_type': 'player',
            'auth_sub': auth_sub,
            'auth_type': 'admin',
            'user_id': user_id,
            'action': 'create',
            'attrib': '',
          }))
          updatePlayersGroupsJson(players_groups=user_dict)
          updatePlayerPools()
          return {
            'statusCode': 201,
            'headers': {'Access-Control-Allow-Origin': origin},
            'body': json.dumps(user_dict, indent=2, default=ddb_default)
          }

        # Update Existing Player
        case 'PUT':
          print('Update Player')
          if (
            not authorize(apiEvent, auth_groups, ['admin']) 
            or (env.MODE not in ['prod', 'sandbox'] and auth_sub != '34f8c488-0061-70bb-a6bd-ca58ce273d9c') # only allow colten in dev/test (or any admin in prod/sandbox)
          ):   
            print(f"WARNING: user_id '{auth_sub}' is not authorized to update players")
            return unauthorized
          
          user_dict = getJsonS3(env.BACKEND_BUCKET, 'players_groups.json')
          data = json.loads(apiEvent['body'])
          user_id = data['user_id']
          attributes = [{'Name': attribute,'Value': value} for attribute, value in data.items() if attribute not in ['groups', 'user_id']]
          attributes.append({'Name': 'sub', 'Value': user_id})
          for attrib in user_dict['Users'][user_id]['Attributes']:
            if attrib['Name'] in ['email_verified', 'phone_number_verified']:
              attributes.append(attrib)

          old_attributes = {attrib['Name']: attrib['Value'] for attrib in user_dict['Users'][user_id]['Attributes']}
          new_attributes = {attrib['Name']: attrib['Value'] for attrib in attributes}
          changes = []
          attrib_changes = []
          if old_attributes != new_attributes:
            diff = compareAttributes(old_attributes, new_attributes)
            # for attribute, value in diff['changed'].items():
            for attribute, value in {**diff['added'], **diff['modified']}.items():
              attrib_changes.append({'Name': attribute, 'Value': value})
              changes.append(attribute)
            for attribute, value in diff['removed'].items():
              attrib_changes.append({'Name': attribute, 'Value': ''})
              changes.append(attribute)

            if 'email' in changes:
              attrib_changes.append({'Name': 'email_verified', 'Value': 'true'})
            
            client = boto3.client('cognito-idp')
            attrib_response = client.admin_update_user_attributes(
              UserPoolId=env.COGNITO_POOL_ID,
              Username=user_id,
              UserAttributes=attrib_changes
            )
            # print(json.dumps({'attrib_changes': attrib_changes, 'attrib_response': attrib_response}, default=ddb_default))
          group_changes = {'added': [], 'removed': []}
          if set(data['groups']) != set(user_dict['Users'][user_id]['groups']):
            changes.append('groups')
            client = boto3.client('cognito-idp')
            # remove user from all groups they are no longer in
            for group in user_dict['Users'][user_id]['groups']:
              if group not in data['groups']:
                client.admin_remove_user_from_group(
                  UserPoolId=env.COGNITO_POOL_ID,
                  Username=user_id,
                  GroupName=group
                )
                group_changes['removed'].append(group)
                changes.append(f'-{group}')
            # add user to all groups they are now in
            for group in data['groups']:
              if group not in user_dict['Users'][user_id]['groups']:
                client.admin_add_user_to_group(
                  UserPoolId=env.COGNITO_POOL_ID,
                  Username=user_id,
                  GroupName=group
                )
                group_changes['added'].append(group)
                changes.append(f'+{group}')
          
          # If attributes changed, update the user_dict
          if attrib_changes != []:
            response = client.admin_get_user(
              UserPoolId=env.COGNITO_POOL_ID,
              Username=user_id,
            )
            user = response
            user['Attributes'] = user['UserAttributes']
            del user['UserAttributes']
            user_dict['Users'][user_id] = {'groups': user_dict['Users'][user_id]['groups'], 'attrib': {}, **user}
            for attrib in user['Attributes']:
              user_dict['Users'][user_id]['attrib'][attrib['Name']] = attrib['Value']
          
          # If groups changed, update the user_dict
          for group in group_changes['added']:
            user_dict['Groups'][group].append(user_id)
            user_dict['Users'][user_id]['groups'].append(group)
          for group in group_changes['removed']:
            user_dict['Groups'][group].remove(user_id)
            user_dict['Users'][user_id]['groups'].remove(group)
          
          if (group_changes['added'] or group_changes['removed']):
            updatePlayerPools()

          print(json.dumps({
            'log_type': 'player',
            'auth_sub': auth_sub,
            'auth_type': 'admin',
            'user_id': user_id,
            'action': 'update',
            'attrib': ', '.join(changes),
          }))
          updatePlayersGroupsJson(players_groups=user_dict)
          return {
            'statusCode': 201,
            'headers': {'Access-Control-Allow-Origin': origin},
            'body': json.dumps(user_dict, indent=2, default=ddb_default)
          }
            

    case '/player/self':
      match method:

        # Player updating their own attributes
        case 'PUT':
          print('Player update own attributes')
          data = json.loads(apiEvent['body'])
          user_id = data['user_id']
          if auth_sub != data['user_id']:
            print(f"WARNING: user_id '{data['user_id']}' does not match auth_sub '{auth_sub}'. not authorized")
            return unauthorized
          user_dict = getJsonS3(env.BACKEND_BUCKET, 'players_groups.json')
          attributes = [{'Name': attribute,'Value': value} for attribute, value in data.items() if attribute not in ['groups', 'user_id', 'accessToken']]
          attributes.append({'Name': 'sub', 'Value': user_id})
          for attrib in user_dict['Users'][user_id]['Attributes']:
            if attrib['Name'] in ['email_verified', 'phone_number_verified']:
              attributes.append(attrib)

          old_attributes = {attrib['Name']: attrib['Value'] for attrib in user_dict['Users'][user_id]['Attributes']}
          new_attributes = {attrib['Name']: attrib['Value'] for attrib in attributes}

          attrib_changes = []
          attrib_response = None
          if old_attributes != new_attributes:
            diff = compareAttributes(old_attributes, new_attributes)
            # for attribute, value in diff['changed'].items():
            for attribute, value in {**diff['added'], **diff['modified']}.items():
              attrib_changes.append({'Name': attribute, 'Value': value})
            for attribute, value in diff['removed'].items():
              attrib_changes.append({'Name': attribute, 'Value': ''})
            try:
              client = boto3.client('cognito-idp')
              attrib_response = client.update_user_attributes(
                UserAttributes=attrib_changes,
                AccessToken=data['accessToken']
              )
              print(json.dumps(attrib_response, default=ddb_default))
            except Exception as e:
              print(e)
              print(json.dumps({
                'request': data, 
                'old_attributes': old_attributes, 
                'new_attributes': new_attributes, 
                'diff': diff, 
                'attrib_changes': attrib_changes
              }, default=ddb_default))
              
              return {
                'statusCode': 400,
                'headers': {'Access-Control-Allow-Origin': origin},
                'body': json.dumps({'message': 'Error updating attributes', 'error': str(e)})
              }
          
          # If attributes changed, update the user_dict
          if attrib_changes != []:
            response = client.admin_get_user(
              UserPoolId=env.COGNITO_POOL_ID,
              Username=user_id,
            )
            user = response
            user['Attributes'] = user['UserAttributes']
            del user['UserAttributes']
            user_dict['Users'][user_id] = {'groups': user_dict['Users'][user_id]['groups'], 'attrib': {}, **user}
            for attrib in user['Attributes']:
              user_dict['Users'][user_id]['attrib'][attrib['Name']] = attrib['Value']

            try:
              print(json.dumps({
                'log_type': 'player',
                'auth_sub': auth_sub,
                'auth_type': 'self',
                'user_id': user_id,
                'action': 'update',
                'attrib': ', '.join([attrib['Name'] for attrib in attrib_changes]),
              }))
            except Exception as e:
              print(json.dumps(attrib_changes))
              raise

            updatePlayersGroupsJson(players_groups=user_dict)
            return {
              'statusCode': 201,
              'headers': {'Access-Control-Allow-Origin': origin},
              'body': json.dumps({'message': 'Attributes Updated', 'response': attrib_response}, indent=2, default=ddb_default)
            }
          else:
            print(json.dumps({
              'old_attributes != new_attributes': old_attributes != new_attributes, 
              'new_attributes': new_attributes,
              'old_attributes': old_attributes
              }, default=ddb_default))
            return {
              'statusCode': 201,
              'headers': {'Access-Control-Allow-Origin': origin},
              'body': json.dumps({'message': 'No Changes'})
            }
    
    case '/gametutorial':
      match method:
        case 'GET':
          print('Get Game Tutorials')
          game_tutorials = getGameTutorials()
          return {
            'statusCode': 200,
            'headers': {'Access-Control-Allow-Origin': origin},
            'body': json.dumps(game_tutorials, default=ddb_default),
          }
        
        case 'PUT':
          print('Update Game Tutorials')
          if not authorize(apiEvent, auth_groups, ['admin']): 
            print(f"WARNING: user_id '{auth_sub}' is not an admin. not authorized")
            return unauthorized
          game_tutorials = getGameTutorials()
          data = json.loads(apiEvent['body'])
          bgg_id = str(data['bgg_id'])
          if bgg_id in game_tutorials:
            action = 'update'
            previous = json.dumps(game_tutorials[bgg_id], default=ddb_default)
          else:
            action = 'create'
            previous = ''
          new = json.dumps(data, default=ddb_default)     
          game_tutorials[bgg_id] = data
          updateGameTutorials(game_tutorials)
          print(json.dumps({
            'log_type': 'game_tutorial',
            'action': action,
            'auth_sub': auth_sub,
            'auth_type': 'admin',
            'previous': previous,
            'new': new,
          }, default=ddb_default))
          return {
            'statusCode': 201,
            'headers': {'Access-Control-Allow-Origin': origin},
            'body': json.dumps(game_tutorials, default=ddb_default),
          }
        
        case 'DELETE':
          print('Delete Game Tutorial')
          if not authorize(apiEvent, auth_groups, ['admin']): 
            print(f"WARNING: user_id '{auth_sub}' is not an admin. not authorized")
            return unauthorized
          game_tutorials = getGameTutorials()
          params = apiEvent.get('queryStringParameters', {})
          bgg_id = str(params['bgg_id'])
          if bgg_id in game_tutorials:
            print(json.dumps({
              'log_type': 'game_tutorial',
              'action': 'delete',
              'auth_sub': auth_sub,
              'auth_type': 'admin',
              'previous': json.dumps(game_tutorials[bgg_id], default=ddb_default),
              'new': '',
            }, default=ddb_default))
            del game_tutorials[bgg_id]
            updateGameTutorials(game_tutorials)
          else:
            print(f"WARNING: Game Tutorial with bgg_id '{bgg_id}' does not exist")
          return {
            'statusCode': 201,
            'headers': {'Access-Control-Allow-Origin': origin},
            'body': json.dumps(game_tutorials, default=ddb_default),
          }

    case '/activitylogs':
      match method:

        # Get activity logs. Admin only
        case 'GET':
          print('Get Activity Logs')          
          if not authorize(apiEvent, auth_groups, ['admin']):
            print(f"WARNING: user_id '{auth_sub}' is not authorized to get activity logs")
            return unauthorized
          
          data = apiEvent['queryStringParameters']
          if data and 'startTime' in data and data['startTime']:
            startTime = int(data['startTime'])
          else:
            delta = timedelta(hours=1)
            # delta = timedelta(minutes=10)
            startTime = int((datetime.now() - delta).timestamp())
          
          # only go back as far as 3/21/24 ~12:37pm
          if startTime < 1711046194: startTime = 1711046194
          
          if data and 'endTime' in data and data['endTime']:
            endTime = int(data['endTime'])
          else:
            endTime = int(datetime.now().timestamp())

          client = boto3.client('logs')
          query = f'fields @timestamp, log_type, action, event_id, date, user_id, action, rsvp, auth_sub, auth_type, previous, new, attrib | filter log_type in ["player", "event", "rsvp", "email_subscription", "game_tutorial"] | sort @timestamp desc'
          log_group = f'/aws/lambda/manage_events_{env.MODE}'
          start_query_response = client.start_query(
              logGroupName=log_group,
              startTime=startTime,
              endTime=endTime,
              queryString=query,
              limit=100
          )
          query_id = start_query_response['queryId']
          response = None
          while response == None or response['status'] == 'Running':
              print('Waiting for query to complete ...')
              time.sleep(1)
              response = client.get_query_results(
                  queryId=query_id
              )
          _response = deepcopy(response)
          _response['results'] = []
          for result in response['results']:
            _result = {}
            for field in result:
              if field['field'] in ['previous', 'new']:
                field['value'] = json.loads(field['value'])
              _result[field['field']] = field['value']
            _response['results'].append(_result)
          # response['results'] = logs
          return {
            'statusCode': 200,
            'headers': {'Access-Control-Allow-Origin': origin},
            'body': json.dumps(_response, default=ddb_default),
          }


    case '/alerts':
      match method:
        case 'GET':
          print('Get Email Alert subscriptions')
          if not authorize(apiEvent, auth_groups, ['admin']):
            print(f"WARNING: user_id '{auth_sub}' is not authorized")
            return unauthorized
          email_alert_preferences = getJsonS3(env.BACKEND_BUCKET, 'email_alert_preferences.json')
          return {
            'statusCode': 200,
            'headers': {'Access-Control-Allow-Origin': origin},
            'body': json.dumps(email_alert_preferences, default=ddb_default),
          }
          
    case '/alerts/player':
      match method:
        case 'GET':
          # if not authorize(apiEvent, auth_groups, ['admin']):
          #   return unauthorized
          print("Get Player's Email Alert subscriptions")
          data = apiEvent['queryStringParameters']
          user_id = data['user_id']
          if auth_sub != data['user_id']:
            print(f"UNAUTHORIZED: user_id '{data['user_id']}' does not match auth_sub '{auth_sub}'")
            return unauthorized
          email_alert_preferences = getJsonS3(env.BACKEND_BUCKET, 'email_alert_preferences.json')
          user_alert_preferences = {}
          for alert_type, subscriber_list in email_alert_preferences.items():
            user_alert_preferences[alert_type] = user_id in subscriber_list
          return {
            'statusCode': 200,
            'headers': {'Access-Control-Allow-Origin': origin},
            'body': json.dumps(user_alert_preferences, default=ddb_default),
          }


        # Update player's email alerts subscriptions
        case 'PUT':
          print("Update Player's email alerts subscriptions")
          data = json.loads(apiEvent['body'])
          user_id = data['user_id']
          if not authorize(apiEvent, auth_groups, ['admin']) and auth_sub != data['user_id']:
            print(f"UNAUTHORIZED: user is not an admin and user_id '{data['user_id']}' does not match auth_sub '{auth_sub}'")
            return unauthorized
          
          if auth_sub == data['user_id']:
            auth_type = 'self'
          else:
            auth_type = 'admin'
          alert_subscriptions = data['alert_subscriptions']
          email_alert_preferences = getJsonS3(env.BACKEND_BUCKET, 'email_alert_preferences.json')
          email_alert_preferences = {alert_type: set(subscriber_list) for alert_type, subscriber_list in email_alert_preferences.items()}

          for alert_type, subscribed in alert_subscriptions.items():
            if alert_type not in email_alert_preferences: 
              # print(f"WARNING: Email Alert type '{alert_type}' does not exist")
              # continue
              email_alert_preferences[alert_type] = set()

            if subscribed:
              if user_id not in email_alert_preferences[alert_type]:
                email_alert_preferences[alert_type].add(user_id)
                print(json.dumps({
                  'log_type': 'email_subscription',
                  'auth_sub': auth_sub,
                  'user_id': data['user_id'],
                  'auth_type': auth_type,
                  'action': 'subscribe',
                  'attrib': alert_type,
                }, default=ddb_default))
            else:
              if user_id in email_alert_preferences[alert_type]:
                email_alert_preferences[alert_type].remove(user_id)
                print(json.dumps({
                  'log_type': 'email_subscription',
                  'auth_sub': auth_sub,
                  'user_id': data['user_id'],
                  'auth_type': auth_type,
                  'action': 'unsubscribe',
                  'attrib': alert_type,
                }, default=ddb_default))

          # Those subscribed to rsvp_all & _debug cannot also be subscribed to rsvp_hosted
          email_alert_preferences['rsvp_hosted'] = email_alert_preferences['rsvp_hosted'] - email_alert_preferences['rsvp_all'] - email_alert_preferences['rsvp_all_debug']
          # Those subscribed to rsvp_all_debug cannot also be subscribed to rsvp_all
          email_alert_preferences['rsvp_all'] = email_alert_preferences['rsvp_all'] - email_alert_preferences['rsvp_all_debug']

          s3 = boto3.client('s3')
          s3.put_object(
            Body=json.dumps(email_alert_preferences, indent=2, default=ddb_default),
            Bucket=env.BACKEND_BUCKET,
            Key='email_alert_preferences.json',
            ContentType='application/json',
            CacheControl='no-cache'
          )
          return {
            'statusCode': 201,
            'headers': {'Access-Control-Allow-Origin': origin},
            'body': json.dumps({'result': 'Alert Subscription(s) Modified'})
          }

  print('Unhandled Method or Path')
  if authorize(apiEvent, auth_groups, ['admin'], log_if_false=False):
    return {
      'statusCode': 200, #204,
      'headers': {'Access-Control-Allow-Origin': origin},
      'body': json.dumps({'auth_groups': auth_groups, 'event': apiEvent}, indent=4),
    }
  else:
    return {
      'statusCode': 204,
      'headers': {'Access-Control-Allow-Origin': origin}
    }
    
# def lambda_handler() 
def updatePlayerPoolsAndPublicEventsJson():
  print('Update Player Pools')
  updatePlayerPools()
  print('Publish public events.json')
  updatePublicEventsJson()

def init_bootstrap():
  from concurrent.futures import ThreadPoolExecutor, as_completed

  s3 = boto3.client('s3')
  print('Initializing email_alert_preferences.json')
  if key_exists(env.BACKEND_BUCKET, 'email_alert_preferences.json'):
    email_alert_preferences = getJsonS3(env.BACKEND_BUCKET, 'email_alert_preferences.json')
    print('Backend email_alert_preferences.json already exists. Skipping')
    print(json.dumps(email_alert_preferences))
  else:
    email_alert_preferences = {
      'rsvp_all_debug': [],
      'rsvp_all': [],
      'rsvp_hosted': []
    }
    s3.put_object(
      Body=json.dumps(email_alert_preferences, indent=2, default=ddb_default),
      Bucket=env.BACKEND_BUCKET,
      Key='email_alert_preferences.json',
      ContentType='application/json',
      CacheControl='no-cache'
    )
    
  print('Initializing players_groups.json')
  try:
    updatePlayersGroupsJson(players_groups=None)
  except:
    user_dict = {'Groups': {}, 'Users': {}}
    updatePlayersGroupsJson(players_groups=user_dict)

  print('Initializing events.json')
  events = getEvents() 
  # print(json.dumps(events, default=ddb_default))
  if events == []:
    initEvent = {
      'game': 'Back To the Future',
      'bgg_id': 302388,
      'attending': [],
      'date': '1955-11-12T10:04:00-06:00',
      'host': 'marty_mcfly',
      'player_pool': [],
      'format': 'Placeholder'
    }
    createEvent(initEvent, process_bgg_id_image=False)
    bgg_update = {'Records': [{'Sns': {'MessageAttributes': {'bgg_id': {'Value': 302388}, 's3_bucket': {'Value': env.S3_BUCKET}}}}]}
  else:
    bgg_update = {'Records': [{'Sns': {'MessageAttributes': {'bgg_id': {'Value': event['bgg_id']}, 's3_bucket': {'Value': env.S3_BUCKET}}}} for event in events if 'bgg_id' in event and event['bgg_id']]}
  
  with ThreadPoolExecutor(max_workers=5) as executor:
    futures = {}
    if len(bgg_update['Records']) > 0:
      client = boto3.client('lambda')
      print(f'Pull {len(bgg_update['Records'])} BGG IDs')
      futures[executor.submit(client.invoke, FunctionName=env.BGG_PICTURE_FN, Payload=json.dumps(bgg_update, default=ddb_default))] = "bgg"
    futures[executor.submit(updatePlayerPoolsAndPublicEventsJson)] = "updatePlayerPoolsAndPublicEventsJson"
    for future in as_completed(futures):
      type = futures[future]
      if type == "bgg":
        print(json.dumps({'BGG pictures result': future.result()}, default=ddb_default))
      elif type == "updatePlayerPoolsAndPublicEventsJson":
        print('Update Player Pools and Public Events JSON complete')

  print('Initializing game_tutorials.json')
  game_tutorials = getGameTutorials()
  
  print('Init Bootstrap Complete')  


def compareAttributes(old_attributes, new_attributes):
  # compare old_attributes:dict to new_attributes:dict
  # return a dict of the differences if any
  diff = {'removed': {}, 'added': {}, 'previous': {}, 'modified': {}}#, 'changed': {}}
  if set(old_attributes.keys()) != set(new_attributes.keys()):
    keys_diff = set(new_attributes.keys()) ^ set(old_attributes.keys())
    for key in keys_diff:
      if key in old_attributes:
        diff['removed'][key] = old_attributes[key] # Attr removed (not in new)
      else:
        diff['added'][key] = new_attributes[key] # Attr added (new only)
  
  keys_same = set(new_attributes.keys()) & set(old_attributes.keys())
  for key in keys_same:
    if key == 'finalScore':
      _old = json.dumps(old_attributes[key])
      _new = json.dumps(new_attributes[key])
    elif isinstance(new_attributes[key], list):
      _old = set(old_attributes[key])
      _new = set(new_attributes[key])
    else:
      _old = old_attributes[key]
      _new = new_attributes[key]

    if _old != _new:
      diff['previous'][key] = old_attributes[key] # previous Attr value (original if different in new)
      diff['modified'][key] = new_attributes[key] # Modified attr value (different in new)

  return diff

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

def authorize(apiEvent, membership:list, filter_groups:list, log_if_false=True ):
  if not membership:
    if log_if_false:
      print(json.dumps({
        'message': 'Not authorized',
        'requestContext': apiEvent['requestContext']
      }))
    return False
    raise Exception('Not Authorized')
  if not set(membership).intersection(set(filter_groups)):
    if log_if_false:
      print(json.dumps({
        'message': 'Not authorized',
        'requestContext': apiEvent['requestContext']
      }))
    return False
    raise Exception('Not Authorized')
  return True

def send_rsvp_sqs(rsvp_dict):
  rsvp_dict = deepcopy(rsvp_dict)    
  # rsvp_dict['timestamp'] = datetime.now().strftime('%Y%m%d%H%M%S%f')
  rsvp_dict['timestamp'] = datetime.now(ZoneInfo('UTC')).isoformat()
  sqs = boto3.client('sqs')
  sqs.send_message(
    QueueUrl=env.RSVP_SQS_URL, 
    MessageBody=json.dumps(rsvp_dict, default=ddb_default),
    MessageGroupId='rsvp',
    # MessageAttributes={key: {'StringValue': value, 'DataType': 'String'} for key, value in rsvp_dict.items()}
  )

def process_rsvp_alert_task():
  client = boto3.client('scheduler', region_name='us-east-1')
  response = client.get_schedule(Name=f'rsvp_alerts_schedule_{env.MODE}', GroupName=f'rsvp_alerts_{env.MODE}')
  current_schedule = response['ScheduleExpression'][3:-1]
  if datetime.fromisoformat(response['ScheduleExpression'][3:-1]+'Z') > datetime.now(ZoneInfo('UTC')):
    print(f'Current rsvp process already scheduled ({current_schedule}) in the future')
    return
  
  # Schedule RSVP alert batch processing for 60 (or 30) seconds in the future
  update_response = client.update_schedule(
    Name=f'rsvp_alerts_schedule_{env.MODE}',
    GroupName=f'rsvp_alerts_{env.MODE}',
    ScheduleExpression=f'at({(datetime.now(ZoneInfo('UTC')) + timedelta(seconds=60 if env.MODE == 'prod' else 30)).isoformat()[:19]})',
    Target=response['Target'],
    FlexibleTimeWindow={'Mode': 'OFF'}
  )
  print(f'Scheduled RSVP alert batch processing for {60 if env.MODE == 'prod' else 30} seconds in the future')
  return
  # print(json.dumps(update_response, default=ddb_default))

def reserved_event_scheduled_tasks_crud(action, params):
  print(f'{action.title()} schedule {params['Name']}')
  client = boto3.client('scheduler', region_name='us-east-1')
  if action == 'create':
    try:
      client.create_schedule(**params)
    except Exception as err:
      if 'ConflictException' in str(err):
        print('WARNING: Create failed with "ConflictException". Trying Update')
        action='update'
        client.update_schedule(**params)
      else: raise
  elif action == 'update':
    try:
      client.update_schedule(**params)
    except Exception as err:
      if 'ResourceNotFoundException' in str(err):
        print('WARNING: Update failed with "ResourceNotFoundException". Trying Create')
        action='create'
        client.create_schedule(**params)
      else: raise
  elif action == 'delete':
    try:
      client.delete_schedule(Name=params['Name'], GroupName=params['GroupName'])
    except Exception as err:
      if 'ResourceNotFoundException' in str(err):
        print('INFO: Delete failed with "ResourceNotFoundException"')
      else: raise
  else:
    raise Exception(f'Invalid action: {action}')
  print(f'{action.title()} schedule {params["Name"]} succeeded')
  return

# is_after_sunday_midnight_of(datetime.fromisoformat(event['date']).replace(tzinfo=ZoneInfo('America/Denver')))
def process_reserved_event_scheduled_tasks(reserved_event, action, target_arn):
  group_name = f'reserved_rsvp_refresh_{env.MODE}'
  acount_id = target_arn.split(':')[4]
  event_date = datetime.fromisoformat(reserved_event['date']).replace(tzinfo=ZoneInfo('America/Denver'))
  base_params = {
    'GroupName':group_name,
    'ScheduleExpressionTimezone':'America/Denver',
    'Target':{
      'Arn': target_arn,
      'RoleArn': f'arn:aws:iam::{acount_id}:role/reserved_rsvp_refresh_scheduler_role_{env.MODE}',
      'Input': json.dumps({'action': 'updatePlayerPools'}),
      'RetryPolicy': {
          'MaximumEventAgeInSeconds': 86400,
          'MaximumRetryAttempts': 185
      },
    },
    'FlexibleTimeWindow':{'Mode': 'OFF'},
    'ActionAfterCompletion':'DELETE',
    'State':'ENABLED',
  }
  for type in ['sunday_prior', 'event_start']:
    _action = action
    params = deepcopy(base_params)
    params['Name'] = f'{type}_{reserved_event['event_id']}'
    if _action == 'delete':
        params = {'Name':params['Name'],'GroupName':group_name}
    elif type == 'sunday_prior':
      sunday_prior = event_date + relativedelta(weekday=SU(-1), hour=0, minute=0, second=0)
      if datetime.now(ZoneInfo('America/Denver')) > sunday_prior:
        if _action == 'create': 
          print(f"INFO: Sunday prior to reserved event ({reserved_event['event_id']}) is in the past. Skipping Sunday refresh")
          continue
        _action = 'delete'
        params = {'Name':params['Name'],'GroupName':group_name}
      else:
        schedule_time = (sunday_prior).isoformat()[:19]
        params['ScheduleExpression'] = f'at({schedule_time})'
        params['Description'] = f'Refresh RSVP eligibility midnight on Sunday ({schedule_time}) prior to the event ({event_date.isoformat()[:19]})'
    elif type == 'event_start':
      if datetime.now(ZoneInfo('America/Denver')) > event_date:
        if _action == 'create': 
          print(f"INFO: Reserved event ({reserved_event['event_id']}) is in the past. Skipping scheduled refresh")
          continue
        _action = 'delete'
        params = {'Name':params['Name'],'GroupName':group_name}
      else:
        schedule_time = (event_date).isoformat()[:19]
        params['ScheduleExpression'] = f'at({schedule_time})'
        params['Description'] = f'Refresh RSVP eligibility after the event starts: {schedule_time}'

    try:
      reserved_event_scheduled_tasks_crud(_action, params)
    except Exception as err:
      # if 'ParamValidationError' in str(err):
      import sys
      err_type  = sys.exc_info()[0]
      print(json.dumps({
        'ERROR': str(err),
        'err_type': str(err_type),
        'type': type,
        '_action': _action,
        'params': params,
      }))
      raise

# Check whether bgg image has already been pulled and send 
# an SNS to trigger pulling/resizing/saving it if not
def process_bgg_id(bgg_id):
  global pull_bgg_pic
  s3 = boto3.client('s3')
  key = f'{bgg_id}.png'
  if not key_exists(env.S3_BUCKET, key):
    pull_bgg_pic = True

    # send message to SNS
    print(f"Sending message to SNS: '{bgg_id}#{env.SNS_TOPIC_ARN}'")
    sns = boto3.client('sns')
    sns.publish(
      TopicArn=env.SNS_TOPIC_ARN,
      Message=f'{bgg_id}#{env.S3_BUCKET}',
      MessageAttributes={
        's3_bucket': {
          'DataType': 'String',
          'StringValue': env.S3_BUCKET
        },
        'bgg_id': {
          'DataType': 'String',
          'StringValue': str(bgg_id)
        }
      }
    )



def waitForBggPic(bgg_id):
   # wait for 5 seconds at most
  for i in range(15):
    if key_exists(env.S3_BUCKET, f'{bgg_id}.png'):
      return
    else:
      print(f"Waiting for {bgg_id}.png to be pulled...")
      time.sleep(.25)


def createEvent(eventDict, process_bgg_id_image=True):
  eventDict = deepcopy(eventDict)    
  event_id = eventDict['event_id'] if 'event_id' in eventDict else str(uuid.uuid4())  # temp: allow supplying event_id for 'Transfer' action. Remove on client side for 'Clone'
  new_event = {
    'event_id': {'S': event_id},
    'event_type': {'S': eventDict['event_type'] if 'event_type' in eventDict else 'GameKnight'},
    'date': {'S': eventDict['date']},
    'host': {'S': eventDict['host']},
    'organizer': {'S': eventDict['organizer']} if 'organizer' in eventDict else {'S': ''},
    'format': {'S': eventDict['format']},
    'open_rsvp_eligibility': {'BOOL': eventDict['open_rsvp_eligibility']} if 'open_rsvp_eligibility' in eventDict else {'BOOL': False},
    'game': {'S': eventDict['game']},
    'attending': {'SS': eventDict['attending']},
    'player_pool': {'SS': eventDict['player_pool']}
  }
  if 'finalScore' in eventDict and eventDict['finalScore'] != '': new_event['finalScore'] = {'S': json.dumps(eventDict['finalScore'])}
  if 'status' in eventDict: new_event['status'] = {'S': eventDict['status']}
  if 'bgg_id' in eventDict: new_event['bgg_id'] = {'N': str(eventDict['bgg_id'])}
  if 'total_spots' in eventDict:  new_event['total_spots'] = {'N': str(eventDict['total_spots'])}
  if 'tbd_pic' in eventDict: new_event['tbd_pic'] = {'S': eventDict['tbd_pic']}
  # if 'migrated' in eventDict: new_event['migrated'] = {'BOOL': eventDict['migrated']}
  if 'not_attending' in eventDict: 
    new_event['not_attending'] = {'SS': eventDict['not_attending']}
  else :
    new_event['not_attending'] = {'SS': ['placeholder']}

  # Make sure 'placeholder' is in not_attending and attending sets (will be deduplicated)
  if 'placeholder' not in new_event['not_attending']['SS']:
    new_event['not_attending']['SS'].append('placeholder')
  if 'placeholder' not in new_event['attending']['SS']:
    new_event['attending']['SS'].append('placeholder')
  if 'placeholder' not in new_event['player_pool']['SS']:
    new_event['player_pool']['SS'].append('placeholder')

  # Start processing download for new game image if necessary
  if process_bgg_id_image and 'bgg_id' in eventDict and eventDict['bgg_id']:
    process_bgg_id(eventDict['bgg_id'])

  ddb = boto3.client('dynamodb', region_name='us-east-1')
  response = ddb.put_item(
    TableName=env.TABLE_NAME,
    Item={**new_event},
    # Fail if item.event_id already exists
    ConditionExpression='attribute_not_exists(event_id)',
  )
  response['event_id'] = event_id
  print('Event Created')

  return response
## def createEvent(eventDict) 


def modifyEvent(eventDict, process_bgg_id_image=True):  
  eventDict = deepcopy(eventDict)             
  modified_event = {
    'event_id': {'S': eventDict['event_id']},
    'event_type': {'S': eventDict['event_type']},
    'date': {'S': eventDict['date']},
    'host': {'S': eventDict['host']},
    'organizer': {'S': eventDict['organizer']} if 'organizer' in eventDict else {'S': ''},
    'format': {'S': eventDict['format']},
    'open_rsvp_eligibility': {'BOOL': eventDict['open_rsvp_eligibility']} if 'open_rsvp_eligibility' in eventDict else {'BOOL': False},
    'game': {'S': eventDict['game']},
    'attending': {'SS': list(eventDict['attending'])},
    'player_pool': {'SS': list(eventDict['player_pool'])},
  }
  if 'finalScore' in eventDict and  eventDict['finalScore'] != '': modified_event['finalScore'] = {'S': json.dumps(eventDict['finalScore'])}
  if 'status' in eventDict: modified_event['status'] = {'S': eventDict['status']}
  if 'bgg_id' in eventDict: modified_event['bgg_id'] = {'N': str(eventDict['bgg_id'])}
  if 'total_spots' in eventDict: modified_event['total_spots'] = {'N': str(eventDict['total_spots'])}
  if 'tbd_pic' in eventDict: modified_event['tbd_pic'] = {'S': eventDict['tbd_pic']}
  # if 'migrated' in eventDict: modified_event['migrated'] = {'BOOL': eventDict['migrated']}
  if 'not_attending' in eventDict: 
    modified_event['not_attending'] = {'SS': list(eventDict['not_attending'])}
  else :
    modified_event['not_attending'] = {'SS': ['placeholder']}

  # Make sure 'placeholder' is in not_attending and attending sets (will be deduplicated)
  if 'placeholder' not in modified_event['not_attending']['SS']:
    modified_event['not_attending']['SS'].append('placeholder')
  if 'placeholder' not in modified_event['attending']['SS']:
    modified_event['attending']['SS'].append('placeholder')
  if 'placeholder' not in modified_event['player_pool']['SS']:
    modified_event['player_pool']['SS'].append('placeholder')

  if process_bgg_id_image and 'bgg_id' in eventDict and eventDict['bgg_id'] and eventDict['bgg_id'] > 0:
    print(json.dumps({"process_bgg_id_image": process_bgg_id_image, "'bgg_id' in eventDict": 'bgg_id' in eventDict, "bgg_id": eventDict['bgg_id']}))
    process_bgg_id(eventDict['bgg_id'])

  # date = parser.parse(text).date().isoformat()
  ddb = boto3.client('dynamodb', region_name='us-east-1')
  response = ddb.put_item(
    TableName=env.TABLE_NAME,
    Item={**modified_event},
    # Fail if item.event_id doesn't already exist
    ConditionExpression='attribute_exists(event_id)',
  )
  print('Event Updated')

  return response
## modifyEvent(eventDict)
  
## Update specific attributes of an event
def updateEvent(event_id, event_updates):
  event_updates = deepcopy(event_updates)
  if 'finalScore' in event_updates and event_updates['finalScore'] != '': event_updates['finalScore'] = json.dumps(event_updates['finalScore'])
  ddb = boto3.resource('dynamodb', region_name='us-east-1')
  table = ddb.Table(env.TABLE_NAME)
  try:
    response = table.update_item(
      Key={ 'event_id': event_id },
      UpdateExpression='SET ' + ', '.join([f'#{k} = :{k}' for k in event_updates.keys()]),
      ConditionExpression=Attr('event_id').exists(),
      ExpressionAttributeValues={
        f':{k}': v for k, v in event_updates.items()
      },
      ExpressionAttributeNames={
        f'#{k}': k for k in event_updates.keys()
      }
    )
  except Exception as e:
    print(e)
    print(json.dumps({'event_updates': event_updates}, default=ddb_default))
    raise e
  print(f'Event {event_id} updated')
  return response
## def updateEvent(event_id, event_updates)


def deleteEvent(event_id):   
  ddb = boto3.resource('dynamodb', region_name='us-east-1')
  table = ddb.Table(env.TABLE_NAME)
  response = table.delete_item(
    Key={ 'event_id': event_id },
    ConditionExpression='attribute_exists (event_id)',
  )
  return response
## def deleteEvent(event_id)

def getEvent(event_id, attributes=[], as_json=False):
  param = {
    "KeyConditionExpression": Key('event_id').eq(event_id)
  }
  if attributes:
    param['ProjectionExpression'] = ','.join([f'#{k}' for k in attributes])
    param['ExpressionAttributeNames'] = {f'#{k}': k for k in attributes}

  ddb = boto3.resource('dynamodb', region_name='us-east-1')
  table = ddb.Table(env.TABLE_NAME)
  response = table.query(**param)
  if len(response['Items']) > 1:
    raise Exception('More than one event found with that ID')
  elif len(response['Items']) == 0:
    raise Exception(f"No event found with ID '{event_id}'")
  
  for event in response['Items']:
    try:
      if 'not_attending' in event and 'placeholder' in event['not_attending']: event['not_attending'].remove('placeholder') 
      if 'attending' in event and 'placeholder' in event['attending']: event['attending'].remove('placeholder')
      if 'player_pool' in event and 'placeholder' in event['player_pool']: event['player_pool'].remove('placeholder') 
      if 'finalScore' in event and event['finalScore']: event['finalScore'] = json.loads(event['finalScore'])
    except:
      print(json.dumps(event, indent=2, default=ddb_default))
      raise
  if as_json:
     return json.dumps(response['Items'][0], default=ddb_default)
  else:
    return response['Items'][0]


def getEvents(dateGte = None, dateLte = None, event_type='GameKnight', as_json=False, tableType=env.MODE):  

  match tableType:
    case env.MODE: table_name=env.TABLE_NAME
    case 'prod': table_name=env.TABLE_NAME_PROD
    case _: raise Exception("Invalid table name")
      
  KeyConditionExpression=(Key('event_type').eq(event_type))
  if dateGte:
    if not isinstance(dateGte, str):
      dateGte = dateGte.isoformat()
    KeyConditionExpression = KeyConditionExpression & Key('date').gte(dateGte)
  if dateLte:
    if not isinstance(dateLte, str):
      dateLte = dateLte.isoformat()
    KeyConditionExpression = KeyConditionExpression & Key('date').lte(dateLte)


  ddb = boto3.resource('dynamodb', region_name='us-east-1')
  table = ddb.Table(table_name)
  response = table.query(
    IndexName='EventTypeByDate',
    Select='ALL_ATTRIBUTES',
    KeyConditionExpression=KeyConditionExpression,
  )
  for event in response['Items']:
    try:
      if 'placeholder' in event['not_attending']: event['not_attending'].remove('placeholder') 
      if 'placeholder' in event['attending']: event['attending'].remove('placeholder')
      if 'placeholder' in event['player_pool']: event['player_pool'].remove('placeholder') 
      if 'finalScore' in event and event['finalScore']: event['finalScore'] = json.loads(event['finalScore'])
    except Exception as e:
      if 'finalScore' in event: print(event['finalScore'])
      print(json.dumps(event, default=ddb_default))
      raise
  if as_json:
     return json.dumps(response['Items'], default=ddb_default)
  else:
    return response['Items']


def updatePublicEventsJson():
  upcoming_and_recent = datetime.now(ZoneInfo("America/Denver")).date() - timedelta(days=14)
  future_events = getEvents(dateGte = upcoming_and_recent.isoformat())
  future_events = [event for event in future_events if event['format'] != 'Private']
  s3 = boto3.client('s3')
  s3.put_object(
    Body=json.dumps(future_events, default=ddb_default),
    Bucket=env.S3_BUCKET,
    Key='events.json',
    ContentType='application/json',
    CacheControl='no-cache',
    # CacheControl='max-age=0, no-cache, no-store, must-revalidate',
  )
  print('events.json updated')


def updatePlayersGroupsJson(players_groups=None):
  if not players_groups:
    players_groups = getAllUsersInAllGroups()
  s3 = boto3.client('s3')
  s3.put_object(
    Body=json.dumps(players_groups, indent=2, default=ddb_default),
    Bucket=env.BACKEND_BUCKET,
    Key='players_groups.json',
    ContentType='application/json',
    CacheControl='no-cache'
  )
  print('Backend players_groups.json updated')

  s3.put_object(
    Body=json.dumps(reduceUserAttrib(players_groups), indent=2, default=ddb_default),
    Bucket=env.S3_BUCKET,
    Key='players_groups.json',
    ContentType='application/json',
    CacheControl='no-cache'
  )
  print('Public players_groups.json updated')
  return players_groups
  


def updateRSVP(event_id, user_id, rsvp):
  now_iso_mt = datetime.now(ZoneInfo("America/Denver")).replace(microsecond=0).isoformat()
  if rsvp == 'attending':
    delete = 'not_attending'
  elif rsvp == 'not_attending':
    delete = 'attending'
  ddb = boto3.resource('dynamodb', region_name='us-east-1')
  table = ddb.Table(env.TABLE_NAME)
  response = table.update_item(
    Key={ 'event_id': event_id },
    UpdateExpression=f'ADD {rsvp} :user_id DELETE {delete} :user_id',
    ConditionExpression=(
      Attr('event_id').exists() & Attr('date').gte(now_iso_mt) &
      (Attr('player_pool').contains(user_id) | Attr('organizer_pool').contains(user_id))),
    ExpressionAttributeValues={
      ':user_id': set([user_id])
    }
  )
  return response

def deleteRSVP(event_id, user_id, rsvp):
  now_iso_mt = datetime.now(ZoneInfo("America/Denver")).replace(microsecond=0).isoformat()
  ddb = boto3.resource('dynamodb', region_name='us-east-1')
  table = ddb.Table(env.TABLE_NAME)
  response = table.update_item(
    Key={ 'event_id': event_id },
    UpdateExpression=f'DELETE {rsvp} :user_id',
    ConditionExpression=(
      Attr('event_id').exists() & Attr('date').gte(now_iso_mt) &
      (Attr('player_pool').contains(user_id) | Attr('organizer_pool').contains(user_id))),
    ExpressionAttributeValues={
      ':user_id': set([user_id])
    }
  )
  return response

def is_after_sunday_midnight_of(given_date):
  # Get Sunday of the same week
  sunday = given_date + relativedelta(weekday=SU(-1), hour=0, minute=0, second=0)

  # Compare current datetime to midnight of that Sunday
  tzinfo = given_date.tzinfo
  if tzinfo in [timezone(timedelta(days=-1, seconds=64800)), timezone(timedelta(days=-1, seconds=61200)), ZoneInfo(key='America/Denver')]:
    return datetime.now(tzinfo) > sunday
  return datetime.now(ZoneInfo("America/Denver")) > sunday


def is_after_6p_day_of(given_date):
  # Get 6pm of the same day
  six_pm = given_date + relativedelta(hour=18, day=given_date.day, month=given_date.month, year=given_date.year)

  # Compare current datetime to midnight of that Sunday
  tzinfo = given_date.tzinfo
  if tzinfo in [timezone(timedelta(days=-1, seconds=64800)), timezone(timedelta(days=-1, seconds=61200)), ZoneInfo(key='America/Denver')]:
    return datetime.now(tzinfo) > six_pm
  return datetime.now(ZoneInfo("America/Denver")) > six_pm
  
def getJsonS3(bucket_name, file_path):
  s3 = boto3.resource('s3')
  content_object = s3.Object(bucket_name, file_path)
  file_content = content_object.get()['Body'].read().decode('utf-8')
  return json.loads(file_content)

def updatePrevSubEvents(events=[], user_cache=True):
  if events == []:
    events = getEvents() # All
  updated_events = set()

  if user_cache:
    user_dict = getJsonS3(env.BACKEND_BUCKET, 'players_groups.json')
  else:
    user_dict = getAllUsersInAllGroups()
  user_prev_sub_dict = {info['attrib']['custom:prev_sub']: player_id for player_id, info in user_dict['Users'].items() if info['attrib'].get('custom:prev_sub', '') != ''}
  if user_prev_sub_dict == {}:
    return updated_events
  
  for event in events:
    event_hash = f'{event['game']}#{event['date']}#{event['event_id']}'
    for k,v in event.items():
      if k in ['event_id', 'event_type', 'date', 'format', 'open_rsvp_eligibility', 'game', 'bgg_id', 'total_spots', 'tbd_pic', 'migrated', 'status']: 
        continue
      if k == 'finalScore':
        for score in v:
          if score['player'] in user_prev_sub_dict and score['player'] not in user_dict:
            updated_events.add(event_hash)
            score['player'] = user_prev_sub_dict[score['player']]
      elif isinstance(v, (list, set)):
        for player_id in v.copy():
          if player_id in user_prev_sub_dict and player_id not in user_dict:
            updated_events.add(event_hash)
            if isinstance(v, list):
              event[k].append(user_prev_sub_dict[player_id])
            if isinstance(v, set):
              event[k].add(user_prev_sub_dict[player_id])
            event[k].remove(player_id)
      elif isinstance(v, str):
        if v in user_prev_sub_dict and v not in user_dict:
          updated_events.add(event_hash)
          event[k] = user_prev_sub_dict[v]
      else:
        raise Exception(f"Unhandled type {type(v)} for {k}: {v}")
    if event_hash in updated_events: 
      print(f"Modify event {event_hash}")
      modifyEvent(event,process_bgg_id_image=False)
  return updated_events

def admin_set_user_password(user_id, user_pool=env.MODE):
  match user_pool:
    case env.MODE: user_pool_id = env.COGNITO_POOL_ID
    case 'prod': user_pool_id = env.COGNITO_POOL_ID_PROD
    case _: raise Exception(f"Invalid user pool: {user_pool}")
  client = boto3.client('cognito-idp', region_name='us-east-1')
  response = client.admin_set_user_password(
      UserPoolId=user_pool_id,
      Username=user_id,
      Password='string',
      Permanent=True
  )

def updatePlayerPools():
  from collections import defaultdict 
  players_groups = getJsonS3(env.S3_BUCKET, 'players_groups.json')
  players = players_groups['Groups']['player']
  organizers = players_groups['Groups']['organizer']
  players_spent = set()
  organizers_spent = set()
  event_updates = defaultdict(dict)
  upcomingEvents = getEvents(dateGte=datetime.now(ZoneInfo("America/Denver")).isoformat()[:19])
  # upcomingEvents = getEvents(dateGte=datetime.now(ZoneInfo("America/Denver")).date()) # 

  # print(json.dumps({
  #   "upcomingEvents": [{'event_id': event['event_id'], 'format': event['format'], 'date': event['date']}  for event in upcomingEvents],
  #   "now": datetime.now(ZoneInfo("America/Denver")).isoformat()[:19],
  #   "in2hr": (datetime.now(ZoneInfo("America/Denver")) + timedelta(hours=2)).isoformat()[:19],
  #   "date": datetime.now(ZoneInfo("America/Denver")).date().isoformat()[:19]
  # }, default=ddb_default))

  ## First round: organizers_spent
  for event in upcomingEvents:
    # Open and open_rsvp_eligibility should have all available players and organizers in their pools
    if (
      event['format'] == 'Open' or 
      (event['format'] == 'Reserved' and 'open_rsvp_eligibility' in event and event['open_rsvp_eligibility'] == True)
    ):
      if set(players) != set(event['player_pool']):
        print(f"event {event['event_id']} update 1")
        event_updates[event['event_id']]['player_pool'] = set(players)
      if 'organizer_pool' not in event or set(organizers) != set(event["organizer_pool"]):
        print(f"event {event['event_id']} update 2")
        event_updates[event['event_id']]['organizer_pool'] = set(organizers)
      
    # If Reserved (but not open_rsvp_eligibility)...
    if event['format'] != 'Reserved': continue
    if 'open_rsvp_eligibility' in event and event['open_rsvp_eligibility'] == True: continue
    # Clear the event organizer if they are not attending or they're now the host
    if event['organizer'] != '' and (event['organizer'] not in event['attending'] or event['organizer'] == event['host']):
      event['organizer'] = ''
      print(f"event {event['event_id']} update 3")
      event_updates[event['event_id']]['organizer'] = ''
      continue
    # Otherwise add the organizer to organizers_spent 
    if event['organizer'] != '': 
      organizers_spent.add(event['organizer'])

  print(json.dumps({"round 1 event_updates": event_updates}, default=ddb_default))

  ## Second round: players_spent and event organizer + organizers_spent
  for event in upcomingEvents:
    # If Reserved (but not open_rsvp_eligibility)...
    if event['format'] != 'Reserved': continue
    if 'open_rsvp_eligibility' in event and event['open_rsvp_eligibility'] == True: continue
    for player in event['attending']:
      if player == event['host']: continue
      # If attending player is an organizer, organizer isnt already being updated, and player isn't already a spent organizer, 
      # add them as the organizer (and as spent)
      if player in organizers:
        if event['organizer'] == '' and player not in organizers_spent:
          event['organizer'] = player
          print(f"event {event['event_id']} update 4")
          event_updates[event['event_id']]['organizer'] = player
          organizers_spent.add(player)
          continue
        # Add player as organizers_spent
        elif event['organizer'] == player:
          organizers_spent.add(player)
          continue
      # Add player as players_spent
      players_spent.add(player)

  print(json.dumps({"round 2 event_updates": event_updates}, default=ddb_default))

  # Round 3. Update Player and Organizer pools
  for event in upcomingEvents:
    # If Reserved (but not open_rsvp_eligibility)...
    if event['format'] != 'Reserved': continue
    if 'open_rsvp_eligibility' in event and event['open_rsvp_eligibility'] == True: continue
    
    # If its after midnight the sunday before the event, open the player and organizer pool if not already
    if is_after_sunday_midnight_of(datetime.fromisoformat(event['date']).replace(tzinfo=ZoneInfo("America/Denver"))):
      if set(players) != set(event["player_pool"]):
        print(f"event {event['event_id']} update 5")
        event_updates[event['event_id']]['player_pool'] = set(players)
      if 'organizer_pool' not in event or set(organizers) != set(event["organizer_pool"]):
        print(f"event {event['event_id']} update 6")
        event_updates[event['event_id']]['organizer_pool'] = set(organizers)
    # Otherwise set each event's player & organizer pool as total_players - spent_players + attending_players
    else:
      player_pool = set(players) - players_spent
      player_pool.update(event['attending'])
      organizer_pool = set(organizers) - organizers_spent
      if event['organizer'] != '': organizer_pool.add(event['organizer'])
      if player_pool != set(event["player_pool"]):
        print(f"event {event['event_id']} update 7")
        event_updates[event['event_id']]['player_pool'] = set(player_pool)
      if 'organizer_pool' not in event or organizer_pool != set(event["organizer_pool"]):
        print(f"event {event['event_id']} update 8")
        event_updates[event['event_id']]['organizer_pool'] = set(organizer_pool)
  
  print(json.dumps({"final event_updates": event_updates}, default=ddb_default))
  # input("Pause")
  for event_id, event_update in event_updates.items():
    if not event_update: print(f"No updates for event {event_id}")
    updateEvent(event_id, event_update)
## end def updatePlayerPools()

def list_groups_for_user(user_id): 
  client = boto3.client('cognito-idp', region_name='us-east-1')
  response = client.admin_list_groups_for_user(
    UserPoolId=env.COGNITO_POOL_ID,
    Username=user_id
  )
  return response['Groups']

def listAllUsers(user_pool=env.MODE):
  match user_pool:
    case env.MODE: user_pool_id = env.COGNITO_POOL_ID
    case 'prod': user_pool_id = env.COGNITO_POOL_ID_PROD
    case _: raise Exception(f"Invalid user pool: {user_pool}")
  client = boto3.client('cognito-idp', region_name='us-east-1')
  response = client.list_users(
    UserPoolId=user_pool_id
  )
  return response
## getAllUsers()

def listAllGroups(user_pool=env.MODE):
  match user_pool:
    case env.MODE: user_pool_id = env.COGNITO_POOL_ID
    case 'prod': user_pool_id = env.COGNITO_POOL_ID_PROD
    case _: raise Exception(f"Invalid user pool: {user_pool}")
  client = boto3.client('cognito-idp', region_name='us-east-1')
  response = client.list_groups(
    UserPoolId=user_pool_id
  )
  return response

def listUsersInGroup(group_name, user_pool=env.MODE):
  match user_pool:
    case env.MODE: user_pool_id = env.COGNITO_POOL_ID
    case 'prod': user_pool_id = env.COGNITO_POOL_ID_PROD
    case _: raise Exception(f"Invalid user pool: {user_pool}")
  client = boto3.client('cognito-idp', region_name='us-east-1')
  response = client.list_users_in_group(
    UserPoolId=user_pool_id,
    GroupName=group_name
  )
  return response['Users']

def getAllUsersInAllGroups(user_pool=env.MODE):
  users = listAllUsers(user_pool=user_pool)
  user_dict = {'Users': {user['Username']: {'groups': set([]), 'attrib': {}, **user} for user in users['Users']}, 'Groups': {}}
  groups = listAllGroups(user_pool=user_pool)
  for group in groups['Groups']:
    user_dict['Groups'][group['GroupName']] = []
    grp_users = listUsersInGroup(group['GroupName'],user_pool=user_pool)
    for user in grp_users:
      user_dict['Users'][user['Username']]['groups'].add(group['GroupName'])
      user_dict['Groups'][group['GroupName']].append(user['Username'])
  for user_id, user in user_dict['Users'].items():
    # user_dict['Users'][user_id]['groups'] = list(user_dict['Users'][user_id]['groups']) in user_dict['Users']:
    for attrib in user['Attributes']:
      user_dict['Users'][user_id]['attrib'][attrib['Name']] = attrib['Value']
  return user_dict

def reduceUserAttrib(user_dict, admin=False):
  users = {'Users': {}, 'Groups': user_dict['Groups']}
  for user_id, user in user_dict['Users'].items():
    try:
      users['Users'][user_id] = {
        'groups': user['groups'],
        'attrib': {
          'given_name': user['attrib']['given_name']
      } }
      if user['attrib'].get('custom:prev_sub'): 
        users['Users'][user_id]['attrib']['custom:prev_sub']= user['attrib']['custom:prev_sub']
      if admin:
        users['Users'][user_id]['attrib'] = user['attrib']
    except:
      print(json.dumps(user, indent=2, default=ddb_default))
      quit()
    # if 'family_name' in user['attrib']: 
    #   users['Users'][user_id]['attrib']['family_name'] = user['attrib']['family_name']
  return users

def updateDates():
  events = getEvents() # All
  for event in events:
    if len(event['date']) <= 19:
      new_date = datetime.fromisoformat(event['date']).replace(
        tzinfo=ZoneInfo("America/Denver"),
        hour=18, minute=0, second=0, microsecond=0
        ).isoformat()
      updateEvent(event['event_id'], {'date': new_date})
      print("from: ", event['date'])
      print("to  : ", new_date, "\n")
    elif "T00:00:00" in event['date']:
      new_date = event['date'].replace("T00:00:00", "T18:00:00")
      updateEvent(event['event_id'], {'date': new_date})
      print("from: ", event['date'])
      print("to  : ", new_date, "\n")
    else:
      print("no change: ", event['date'], "\n")


def replaceUserId(old_user_id, new_user_id, events=None):
  update_log = []
  if events is None:
    events = getEvents() # All
  for event in events:
    update = False
    if old_user_id in event['attending']:
      event['attending'].remove(old_user_id)
      event['attending'].add(new_user_id)
      update_log.append(f'Updated {event["event_id"]} ({event["game"]}) attending from {old_user_id} to {new_user_id}')
      update = True
    if old_user_id in event['not_attending']:
      event['not_attending'].remove(old_user_id)
      event['not_attending'].add(new_user_id)
      update_log.append(f'Updated {event["event_id"]} ({event["game"]}) not attending from {old_user_id} to {new_user_id}')
      update = True
    if old_user_id in event['player_pool']:
      event['player_pool'].remove(old_user_id)
      event['player_pool'].add(new_user_id)
      update_log.append(f'Updated {event["event_id"]} ({event["game"]}) player pool from {old_user_id} to {new_user_id}')
      update = True
    if old_user_id == event['host']:
      event['host'] = new_user_id
      update_log.append(f'Updated {event["event_id"]} ({event["game"]}) host from {old_user_id} to {new_user_id}')
      update = True
    if old_user_id == event['organizer']:
      event['organizer'] = new_user_id
      update_log.append(f'Updated {event["event_id"]} ({event["game"]}) organizer from {old_user_id} to {new_user_id}')
      update = True
    if update:
      event['not_attending'] = list(event['not_attending'])
      event['attending'] = list(event['attending'])
      event['player_pool'] = list(event['player_pool'])
      modifyEvent(event, process_bgg_id_image=False)
  return update_log

def getGameTutorials():
  try:
    return getJsonS3(env.S3_BUCKET, 'game_tutorials.json')
  except botocore.exceptions.ClientError as e:
    if e.response['Error']['Code'] == 'NoSuchKey':
      print("game_tutorials.json does not exist. Creating and Returning empty dictionary.")
      updateGameTutorials({})
      return {}
    else:
      raise

def updateGameTutorials(game_tutorials):
  s3 = boto3.client('s3')
  s3.put_object(
    Body=json.dumps(game_tutorials, indent=2, default=ddb_default),
    Bucket=env.S3_BUCKET,
    Key='game_tutorials.json',
    ContentType='application/json',
    CacheControl='no-cache'
  )
  print('game_tutorials.json updated')


if __name__ == '__main__':
  # email_alert_preferences = {
  #   "rsvp_all_debug": [],
  #   "rsvp_all": [],
  #   "rsvp_hosted": []
  # }
  # s3 = boto3.client('s3')
  # s3.put_object(
  #   Body=json.dumps(email_alert_preferences, indent=2, default=ddb_default),
  #   Bucket=env.BACKEND_BUCKET,
  #   Key='email_alert_preferences.json',
  #   ContentType='application/json',
  #   CacheControl='no-cache'
  # )
  # print("email_alert_preferences.json uploaded")
  # quit()
  
  # all_events = getEvents()
  # # print(json.dumps(all_events, indent=2, default=ddb_default))
  # old_user_id = '9458a4e8-e071-7065-e414-b1cc942592ec'
  # new_user_id = '8468c468-d0d1-7097-82fa-f70d391b0e53'
  # update_log = replaceUserId(old_user_id, new_user_id, events=all_events)
  # print(json.dumps(update_log, indent=2))
  # quit()

  # print(datetime.now(ZoneInfo("UTC")).isoformat())
  # print(datetime.now().isoformat())
  # quit()
  # client = boto3.client('scheduler', region_name='us-east-1')
  # response = client.get_schedule(
  #   # GroupName='string',
  #   Name='rsvp_alerts_schedule_dev'
  # )
  # response = client.list_schedules(
  #   # GroupName='string',
  #   # MaxResults=123,
  #   # NamePrefix='string',
  #   # NextToken='string',
  #   State='DISABLED'
  # )

  # test={
  #   # "Arn": "arn:aws:scheduler:us-east-1:569879156317:schedule/default/rsvp_alerts_schedule_dev",
  #   # "CreationDate": "2024-04-01T21:29:16.524000-06:00",
  #   # "GroupName": "default",
  #   # "LastModificationDate": "2024-04-01T21:29:16.524000-06:00",
  #   # "State": "DISABLED",
  #   "Name": "rsvp_alerts_schedule_dev",
  #   "ScheduleExpression": "at(yyyy-mm-ddThh:mm:ss)",
  #   "Target": {
  #     "Arn": "arn:aws:lambda:us-east-1:569879156317:function:rsvp_alerts_dev",
  #     "RoleArn": "arn:aws:iam::569879156317:role/DEVGameKnightsEventsAPI-RsvpAlertsFunctionScheduleE-k3D73wZ1kmkS"
  #   }
  # }
    # datetime.fromisoformat(data['date']).replace(tzinfo=ZoneInfo("America/Denver")).isoformat()
  # print(response['ScheduleExpression'][3:-1])
  # print(datetime.fromisoformat(response['ScheduleExpression'][3:-1]+"Z") )
  # print(datetime.now(ZoneInfo("UTC")))
  # print(datetime.fromisoformat(response['ScheduleExpression'][3:-1]+"Z") > datetime.now(ZoneInfo("UTC")))
  # print(json.dumps(response, indent=2, default=ddb_default))
  # print(datetime.now(ZoneInfo("UTC")).isoformat()[:19])
  # print((datetime.now(ZoneInfo("UTC")) + timedelta(minutes=5)).isoformat()[:19])
  # now = datetime.now()
  # date_string = now.strftime("%Y%m%d%H%M%S%f")
  # # print(date_string)
  # date_int = int(date_string)
  # print(date_int)
  # print(int(datetime.now().strftime("%Y%m%d%H%M%S%f")))

  quit()

  all_events = getEvents()
  for event in all_events:
    if 'attending' not in event:
      print(json.dumps(event, indent=2, default=ddb_default))
    if 'not_attending' not in event:
      print(json.dumps(event, indent=2, default=ddb_default))

              # startTime=int((datetime.today() - timedelta(hours=5)).timestamp()),
              # endTime=int(datetime.now().timestamp()),
  # print (((datetime.today() - timedelta(hours=5)).timestamp()), (datetime.now().timestamp()))
  # print (int((datetime.today() - timedelta(hours=5)).timestamp()), int(datetime.now().timestamp()))

  # print(int(datetime.now().timestamp()))

  # print(timedelta(hours=1))
  # print(((datetime.now() - timedelta(hours=1)).isoformat()), (datetime.now().isoformat()))
  # print(int((datetime.now() - timedelta(hours=1)).timestamp()), int(datetime.now().timestamp()))
  quit()


  # event_date = '2024-02-16T00:00:00'
  # # event_date = '2024-03-16T05:00:00-06:00'
  # print(event_date)
  # print(datetime.fromisoformat(event_date).replace(
  #   tzinfo=ZoneInfo("America/Denver"),
  #   hour=18, minute=0, second=0, microsecond=0
  #   ).isoformat())


  # print(datetime.now(ZoneInfo("America/Denver")).replace(microsecond=0).isoformat())
  # print(datetime.now(ZoneInfo("America/Denver")).isoformat())
  # print(is_after_6p_day_of(datetime.fromisoformat(event_date)))
  quit()
  print(event_date)
  print(len(event_date))
  print(datetime.fromisoformat(event_date))# == timezone(timedelta(days=-1, seconds=64800)))
  print(datetime.fromisoformat(event_date).replace(tzinfo=ZoneInfo("America/Denver")))

  var_tzinfo = datetime.fromisoformat(event_date).tzinfo

  var2_tzinfo = datetime.fromisoformat(event_date).replace(tzinfo=ZoneInfo("America/Denver")).tzinfo

  print(datetime.fromisoformat(event_date).tzinfo in [timezone(timedelta(days=-1, seconds=64800)), timezone(timedelta(days=-1, seconds=61200)), ZoneInfo(key='America/Denver')])
  print([
    var_tzinfo,
    type(var_tzinfo),
    var2_tzinfo,
    type(var2_tzinfo),

  ])
  # print(is_after_sunday_midnight_of(datetime.fromisoformat(event_date)))

  
  
  # if is_after_sunday_midnight_of(datetime.fromisoformat(event_date).replace(tzinfo=ZoneInfo("America/Denver"))):
  # if is_after_sunday_midnight_of(datetime.fromisoformat(event_date)):
  
  quit()

  ## Dev:
  # # export sqs_url=https://sqs.us-east-1.amazonaws.com/569879156317/bgg_picture_sqs_queue_dev 
  # export s3_bucket=cdkstack-bucketdevff8a9acd-pine3ubqpres
  # export table_name=game_events_dev      
  # export backend_bucket=dev-cubes-and-cardboard-backend
  # export sns_topic=arn:aws:sns:us-east-1:569879156317:BggPictureSnsTopic_dev
  # export rsvp_sqs_url=https://sqs.us-east-1.amazonaws.com/569879156317/sqs_rsvp_alerts_dev.fifo  
  # export mode=dev

  # # Prod:
  # # export sqs_url=https://sqs.us-east-1.amazonaws.com/569879156317/bgg_picture_sqs_queue
  # export s3_bucket=cdkstack-bucket83908e77-7tr0zgs93uwh
  # export table_name=game_events
  # export backend_bucket=prod-cubes-and-cardboard-backend
  # export sns_topic=arn:aws:sns:us-east-1:569879156317:BggPictureSnsTopic_prod 
  # export rsvp_sqs_url=placeholder
  # export mode=prod
  
  updatePublicEventsJson()
  updatePlayersGroupsJson()
