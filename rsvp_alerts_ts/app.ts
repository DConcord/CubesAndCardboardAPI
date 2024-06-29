import { APIGatewayProxyEvent, APIGatewayProxyResult } from 'aws-lambda';
import { SQSClient, ReceiveMessageCommand, DeleteMessageCommand } from "@aws-sdk/client-sqs";
import { S3Client, GetObjectCommand } from "@aws-sdk/client-s3"; 
import { SESv2Client, SendEmailCommand } from "@aws-sdk/client-sesv2"; 
import { GetItemCommand, GetItemInput, DynamoDBClient, QueryCommand, QueryInput } from "@aws-sdk/client-dynamodb"; 
// import { DynamoDBDocumentClient } from "@aws-sdk/lib-dynamodb"
import { marshall, unmarshall } from "@aws-sdk/util-dynamodb"
import { NodeJsClient } from "@smithy/types";

import * as yaml from "js-yaml";
import { exit } from 'process';



// export TABLE_NAME=game_events_dev      
// export S3_BUCKET=cdkstack-bucketdevff8a9acd-pine3ubqpres
// export RSVP_SQS_URL=p

const RSVP_SQS_URL = process.env.RSVP_SQS_URL;
const S3_BUCKET = process.env.S3_BUCKET;
const TABLE_NAME = process.env.TABLE_NAME // 'game_events'

/**
 *
 * Event doc: https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-lambda-proxy-integrations.html#api-gateway-simple-proxy-for-lambda-input-format
 * @param {Object} event - API Gateway Lambda Proxy Input Format
 *
 * Return doc: https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-lambda-proxy-integrations.html
 * @returns {Object} object - API Gateway Lambda Proxy Output Format
 *
 */
const config = {
  region: "us-east-1",
} 

const rsvp_change = {
  attending: "not attending",
  not_attending: "attending",
};

const sqs = new SQSClient(config);
const s3 = new S3Client(config) as NodeJsClient<S3Client>;
const ses = new SESv2Client(config);
const ddb = new DynamoDBClient(config); // BareBones
// const ddb = new DynamoDB() // Full
// const ddbDocClient = DynamoDBDocumentClient.from(ddb); // client is DynamoDB client

async function getEvent(event_id:string, attributes = [], asJson = false): Promise<ExistingGameKnightEventDDB | undefined> {
  const getItemInput:GetItemInput = {
    TableName: TABLE_NAME, 
    Key: marshall({event_id: event_id})
  };

  if (attributes.length > 0) {
    getItemInput.ProjectionExpression = attributes.join(',');
  }

  const getItemCommand = new GetItemCommand(getItemInput);

  try {
    const { Item } = await ddb.send(getItemCommand);
    if (!Item) return undefined

    const event:ExistingGameKnightEventDDB = unmarshall(Item) as ExistingGameKnightEventDDB

    if (event.not_attending.has('placeholder')) {
      event.not_attending.delete('placeholder');
    }
    if (event.attending.has('placeholder')) {
      event.attending.delete('placeholder');
    }
    if (event.player_pool.has('placeholder')) {
      event.player_pool.delete('placeholder');
    }
    // if (event.finalScore) {
    //   event.finalScore = JSON.parse(event.finalScore); 
    // }


    if (asJson) {
      // return JSON.stringify(event);
    } else {
      return event;
    }

  } catch (err) {
    console.error(err);
    throw err;
  }

}

if (typeof require !== 'undefined' && require.main === module) {
  myMain();
}
async function myMain() {
  // const event = await getEvent("ef7f6d43-64d8-4a3e-bc15-61a6ea9b0fd5")
  // console.log(event)
  exit
}

const SendEmail = async ({text, html}: {text: string, html: string}) => {

  // const { SESv2Client, SendEmailCommand } = require("@aws-sdk/client-sesv2"); // CommonJS import
  const SendEmailRequest = { // SendEmailRequest
    FromEmailAddress: "Cubes and Cardboard RSVP Alert <alert@mail.cubesandcardboard.net>",
    Destination: { // Destination
      ToAddresses: [ // EmailAddressList
        "colten@thepeaks.me",
      ]
    },
    Content: { // EmailContent
      Simple: { // Message
        Subject: { // Content
          Data: "RSVP Alert", // required
        },
        Body: { // Body
          Text: {
            Data: text, // required
            // Charset: "STRING_VALUE",
          },
          Html: {
            Data: html, // required
            // Charset: "STRING_VALUE",
          },
        },
        // Headers: [ // MessageHeaderList
        //   { // MessageHeader
        //     Name: "STRING_VALUE", // required
        //     Value: "STRING_VALUE", // required
        //   },
        // ],
      },
    },
    // EmailTags: [ // MessageTagList
    //   { // MessageTag
    //     Name: "STRING_VALUE", // required
    //     Value: "STRING_VALUE", // required
    //   },
    // ],
    // ConfigurationSetName: "STRING_VALUE",
    // ListManagementOptions: { // ListManagementOptions
    //   ContactListName: "STRING_VALUE", // required
    //   TopicName: "STRING_VALUE",
    // },
  };
  const response = await ses.send(new SendEmailCommand(SendEmailRequest));
  return response

}


async function GetS3Object(Key: string){
  const response = await s3.send(
    new GetObjectCommand({
      Bucket: S3_BUCKET,
      Key: Key,
    }),
  )
  const body = await response.Body!.transformToString();
  // console.log(body)
  return body;
}

// const GetS3Object = async (Key: string, { json }: { json: boolean }) => {
//   const response = await s3.send(new GetObjectCommand({ 
//     Bucket: S3_BUCKET,
//     Key: Key
//   }))
//   console.log(response)
//   console.log(response.Body!)
//   if (json){
//     console.log(JSON.parse(response.Body!.toString()))
//     return JSON.parse(response.Body!.toString())
//   }
//   return response.Body
// };
// const response = await client.send(command);

const DeleteMessage = (ReceiptHandle: string ) => new DeleteMessageCommand({
  QueueUrl: RSVP_SQS_URL,
  ReceiptHandle: ReceiptHandle
})

const ReceiveMessage = () => new ReceiveMessageCommand({ // ReceiveMessageRequest
  QueueUrl: RSVP_SQS_URL, // required
  MaxNumberOfMessages: 10,
  WaitTimeSeconds: 10,
});

export const lambdaHandler = async (event: APIGatewayProxyEvent): Promise<APIGatewayProxyResult> => {
  try {
    const messages = []
    let response = await sqs.send(ReceiveMessage())
    if (response.Messages){
      messages.push(...response.Messages)
    }

    while (response.Messages && response.Messages.length == 10){
      response = await sqs.send(ReceiveMessage())
      if (response.Messages){
        messages.push(...response.Messages)
      }
    }
    console.log(messages)

    const rsvpLogs:RsvpLogType[] = []
    for (const message of messages){
      rsvpLogs.push(JSON.parse(message.Body!))
      await sqs.send(DeleteMessage(message.ReceiptHandle!))
      // console.log(message)
    }
    const events:ExistingGameKnightEvent[] = JSON.parse(await GetS3Object("events.json"))
    const eventsDicts:EventDict = Object.fromEntries(events.map(event => [event.event_id, event]))
    const players_groups:PlayersGroups = JSON.parse(await GetS3Object("players_groups.json") )
    const playersDict = players_groups.Users 

    console.log(events)
    console.log(players_groups)
    console.log(rsvpLogs)

    // const rsvp_hash = Object.fromEntries(rsvpLogs.map(log => [[log.event_id, log.user_id], log]))
    // console.log(rsvp_hash)

    const rsvp_readable:{[key: string]:string[]} = {} 
    for (const log of rsvpLogs) {
      const event = log.event_id in eventsDicts ?  eventsDicts[log.event_id] : await getEvent(log.event_id)
      
      // if (event) var event_str = `Date: ${formatIsoDate(log.date)}, Game: ${event.game}, Host: ${playersDict[event.host].attrib.given_name}:`
      // else event_str = `Date: ${formatIsoDate(log.date)}`
      const event_str = event 
        ? `Date: ${formatIsoDate(log.date)}, Game: ${event.game}, Host: ${playersDict[event.host].attrib.given_name}:`
        : `Date: ${formatIsoDate(log.date)}`
        
      if (!(event_str in rsvp_readable)) rsvp_readable[event_str] = []

      const rsvp = log.rsvp.replace("_", " ")
      const timestamp = new Date(log["timestamp"]).toLocaleString("lt", { timeZone: "America/Denver", timeZoneName: "short" })
      var subject;
      var verb;
      var object; 
      var pronoun = "his"
      var original;
      var result;
      var sentence = "";
      switch (log.auth_type){
        case "self":
          subject = playersDict[log.user_id].attrib.given_name
          object = pronoun
          break;
        default:
          subject = `${playersDict[log.auth_sub].attrib.given_name} (${log.auth_type})`
          if (playersDict[log.user_id].attrib.given_name.endsWith("s")){
            object = playersDict[log.user_id].attrib.given_name + "'"
          } else {
            object = playersDict[log.user_id].attrib.given_name + "'s"
          }
          break;
      }

      switch (log.action) {
        case "delete":
          verb = "changed"
          original = rsvp 
          result = "undecided"
          sentence = `${timestamp}: ${subject} ${verb} ${object} RSVP from '${original}' to '${result}'`
          break;
        case "add":
          verb = "marked"
          result = rsvp
          sentence = `${timestamp}: ${subject} ${verb} ${object} RSVP as '${result}'`
          break;
        case "update":
          verb = "changed"
          original = rsvp_change[log.rsvp]
          result = rsvp
          sentence = `${timestamp}: ${subject} ${verb} ${object} RSVP from '${original}' to '${result}'`
          break;
      }
      rsvp_readable[event_str].push(sentence) 
    }

    const rsvp_readable_html:string = Object.entries(rsvp_readable).map(([event, sentences]) => {
      let _string = `<h2>${event}</h2>`
      const _sentences = sentences.map(sentence => `<p>${sentence}</p>`).join("")
      return _string + _sentences
    }).join("")
    console.log(rsvp_readable)
    const ses_response = await SendEmail({text: yaml.dump(rsvp_readable, { indent: 2 }), html: rsvp_readable_html})
    console.log(ses_response)
    
    // {
    //   log_type: 'rsvp',
    //   auth_sub: '34f8c488-0061-70bb-a6bd-ca58ce273d9c',
    //   auth_type: 'self',
    //   event_id: 'edf4a28a-2a8e-4a95-bf5b-a69725e07d8e',
    //   date: '2024-04-25T18:00:00-06:00',
    //   user_id: '34f8c488-0061-70bb-a6bd-ca58ce273d9c',
    //   action: 'update',
    //   rsvp: 'not_attending'
    // }
    // for (const log of rsvpLogs){
    //   console.log(log)
    // }

    return {
      statusCode: 200,
      body: "Success",
    };
  } catch (err) {
    console.log(err);
    return {
      statusCode: 500,
      body: JSON.stringify({
        message: 'some error happened',
      }),
    };
  }
};

function formatIsoDate(isoString: string) {
  return new Date(isoString).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "America/Denver",
  });
}


type LogType = {
  timestamp: string;
  log_type: "event" | "rsvp" | "player";
  date: string;
  action: "create" | "update" | "delete" | "modify" | "add";
  auth_sub: string;
  auth_type: "admin" | "self" | "host";
  previous: Object;
  new: Object;
  event_id: string;
  user_id: string;
  rsvp: "attending" | "not_attending";
  attrib: string;
};
type RsvpLogType = Omit<LogType, "previous" | "new" | "attrib">;
type EventLogType = Omit<LogType, "event_id" | "user_id" | "rsvp" | "attrib">;
type PlayerLogType = Omit<LogType, "date" | "previous" | "new" | "event_id" | "rsvp">;


export type PlayersGroups = {
  Users: PlayersDict;
  Groups: {
    [key: string]: string[];
  };
};

export type PlayersDict = {
  [key: string]: PlayerGet;
};

export type PlayerGet = {
  groups: string[];
  attrib: {
    given_name: string;
    family_name?: string;
    email: string;
    phone_number?: string;
  };
};

export interface EventDict {
  [key: ExistingGameKnightEvent["event_id"]]: ExistingGameKnightEvent;
}

export interface ExistingGameKnightEvent extends GameKnightEvent {
  event_id: string;
}
export interface ExistingGameKnightEventDDB extends Omit<GameKnightEvent, 'attending' | 'not_attending' | 'player_pool' | 'organizer_pool'>   {
  event_id: string;
  attending: Set<string>;
  not_attending: Set<string>;
  player_pool: Set<string>;
  organizer_pool: Set<string>;
}

export type GameKnightEvent = {
  event_id?: string;
  event_type: string;
  date: string;
  host: string;
  organizer: string;
  format: "Open" | "Reserved" | "Private";
  game: string;
  bgg_id?: number;
  total_spots?: number;
  registered?: string[];
  attending: string[];
  not_attending: string[];
  player_pool: string[];
  organizer_pool: string[];
  tbd_pic?: string;
  migrated?: boolean;
  status?: "Normal" | "Cancelled";
  // finalScore?: PlayerScore[];
};