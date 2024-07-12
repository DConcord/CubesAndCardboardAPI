import { APIGatewayProxyEvent, APIGatewayProxyResult } from "aws-lambda";
import { SQSClient, ReceiveMessageCommand, Message, DeleteMessageCommand } from "@aws-sdk/client-sqs";
import { S3Client, GetObjectCommand } from "@aws-sdk/client-s3";
import { SESv2Client, SendEmailCommand } from "@aws-sdk/client-sesv2";
import { GetItemCommand, GetItemInput, DynamoDBClient } from "@aws-sdk/client-dynamodb";
import { marshall, unmarshall } from "@aws-sdk/util-dynamodb";
import { NodeJsClient } from "@smithy/types";
// import "source-map-support/register";

import * as yaml from "js-yaml";
import { exit } from "process";

// export RSVP_SQS_URL=p
// export S3_BUCKET=cdkstack-bucketdevff8a9acd-pine3ubqpres
// export TABLE_NAME=game_events_dev

const MODE = process.env.MODE!;
const RSVP_SQS_URL = process.env.RSVP_SQS_URL!;
const S3_BUCKET = process.env.S3_BUCKET!;
const TABLE_NAME = process.env.TABLE_NAME!; // 'game_events'
const BACKEND_BUCKET = process.env.BACKEND_BUCKET!;

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
};

const rsvp_change = {
  attending: "not_attending" as "not_attending",
  not_attending: "attending" as "attending",
};

const sqs = new SQSClient(config);
const s3 = new S3Client(config) as NodeJsClient<S3Client>;
const ses = new SESv2Client(config);
const ddb = new DynamoDBClient(config); // BareBones

// Retrieve GameKnightEvent from DynamoDB
async function getEvent(event_id: string, attributes = []): Promise<ExistingGameKnightEventDDB | undefined> {
  const getItemInput: GetItemInput = {
    TableName: TABLE_NAME,
    Key: marshall({ event_id: event_id }),
  };

  if (attributes.length > 0) {
    getItemInput.ProjectionExpression = attributes.join(",");
  }

  const getItemCommand = new GetItemCommand(getItemInput);

  try {
    const { Item } = await ddb.send(getItemCommand);
    if (!Item) return undefined;

    const event: ExistingGameKnightEventDDB = unmarshall(Item) as ExistingGameKnightEventDDB;

    if (event.not_attending.has("placeholder")) {
      event.not_attending.delete("placeholder");
    }
    if (event.attending.has("placeholder")) {
      event.attending.delete("placeholder");
    }
    if (event.player_pool.has("placeholder")) {
      event.player_pool.delete("placeholder");
    }
    // if (event.finalScore) {
    //   event.finalScore = JSON.parse(event.finalScore);
    // }

    return event;
  } catch (err) {
    console.error(err);
    throw err;
  }
}

// run myMain() when running the script directly from local dev cli
if (typeof require !== "undefined" && require.main === module) {
  myMain();
}
async function myMain() {
  // const event = await getEvent("ef7f6d43-64d8-4a3e-bc15-61a6ea9b0fd5")
  // console.log(event)
  exit;
}

interface SendEmailProps {
  fromAddress?: string;
  toAddresses: string[];
  subject?: string;
  textBody: string;
  htmlBody: string;
}

const SendEmail = async ({
  fromAddress = MODE === "dev"
    ? "Game Knight DEV RSVP Alert <alert@mail.cubesandcardboard.net>"
    : "Game Knight RSVP Alert <alert@mail.cubesandcardboard.net>",
  toAddresses,
  subject = MODE === "dev" ? "DEV RSVP Alert" : "RSVP Alert",
  textBody,
  htmlBody,
}: SendEmailProps) => {
  const SendEmailRequest = {
    FromEmailAddress: fromAddress,
    Destination: {
      ToAddresses: toAddresses,
    },
    Content: {
      Simple: {
        Subject: {
          Data: subject,
        },
        Body: {
          Text: {
            Data: textBody,
          },
          Html: {
            Data: htmlBody,
          },
        },
        // Headers: [
        //   // MessageHeaderList
        //   {
        //     // MessageHeader
        //     Name: " X-Entity-Ref-ID", // required
        //     Value: "RSVP_Alert", // required
        //   },
        // ],
      },
    },
  };
  const response = await ses.send(new SendEmailCommand(SendEmailRequest));
  return response;
};

async function GetS3Object(Key: string, Bucket: string) {
  const response = await s3.send(
    new GetObjectCommand({
      Bucket: Bucket, // S3_BUCKET,
      Key: Key,
    })
  );
  const body = await response.Body!.transformToString();
  // console.log(body)
  return body;
}

const DeleteMessage = (ReceiptHandle: string) =>
  new DeleteMessageCommand({
    QueueUrl: RSVP_SQS_URL,
    ReceiptHandle: ReceiptHandle,
  });

const ReceiveMessage = () =>
  new ReceiveMessageCommand({
    QueueUrl: RSVP_SQS_URL, // required
    MaxNumberOfMessages: 10,
    WaitTimeSeconds: 10,
  });

export const lambdaHandler = async (event: APIGatewayProxyEvent): Promise<APIGatewayProxyResult> => {
  try {
    // const messages: Message[] = [];
    const rsvpLogs: RsvpLogType[] = [];

    let start = true;
    let response;
    while (start || (response!.Messages && response!.Messages.length == 10)) {
      console.log("Retrieving Messages");
      response = await sqs.send(ReceiveMessage());
      if (response.Messages) {
        console.log(`response.Messages count: ${response.Messages.length}`);
        // messages.push(...response.Messages);

        let awaitDeleteMessages = [];
        for (const message of response.Messages) {
          rsvpLogs.push(JSON.parse(message.Body!));
          awaitDeleteMessages.push(sqs.send(DeleteMessage(message.ReceiptHandle!)));
        }
        await Promise.allSettled(awaitDeleteMessages);
      } else {
        if (start) return { statusCode: 200, body: JSON.stringify({ message: "No new RSVP Messages" }) };
        console.log("No more messages");
      }
      start = false;
    }
    console.log(`Total Messages: ${rsvpLogs.length}`);
    // console.log(messages);

    const RetrieveS3 = await Promise.allSettled([
      GetS3Object("events.json", S3_BUCKET),
      GetS3Object("players_groups.json", BACKEND_BUCKET),
      GetS3Object("email_alert_preferences.json", BACKEND_BUCKET),
    ]);
    console.log("%j", { RetrieveS3: RetrieveS3 });
    const events: ExistingGameKnightEvent[] = RetrieveS3[0].status === "fulfilled" && JSON.parse(RetrieveS3[0].value);
    const players_groups: PlayersGroups = RetrieveS3[1].status === "fulfilled" && JSON.parse(RetrieveS3[1].value);
    const email_alert_preferences: AllEmailAlertPreferences =
      RetrieveS3[2].status === "fulfilled" && JSON.parse(RetrieveS3[2].value);

    const eventsDict: EventDict = Object.fromEntries(events.map((event) => [event.event_id, event]));
    const playersDict = players_groups.Users;

    const rsvpFinal: RsvpFinalType = {};
    const rsvpReadable: { [key: string]: string[] } = {};
    for (const log of rsvpLogs) {
      if (!(log.event_id in eventsDict)) {
        console.log(`retrieving event ${log.event_id}`);
        const getEventResult = await getEvent(log.event_id);
        if (getEventResult) {
          eventsDict[log.event_id] = getEventResult;
        } else {
          console.log(`ERROR: Event ${log.event_id} not found`);
          continue;
        }
      }
      const event = eventsDict[log.event_id];
      if (!(log.event_id in rsvpFinal)) rsvpFinal[log.event_id] = {};
      if (!(log.user_id in rsvpFinal[log.event_id]))
        rsvpFinal[log.event_id][log.user_id] = { originalRsvp: "", finalRsvp: "", finalSentence: "" };

      const event_str = event ? `${event.game} (${formatIsoDate(event.date)})` : `Date: ${formatIsoDate(log.date)}`;
      if (!(event_str in rsvpReadable)) rsvpReadable[event_str] = [];
      const rsvp = log.rsvp.replace("_", " ");

      const timestamp = new Date(log["timestamp"]).toLocaleString("en-US", {
        timeZone: "America/Denver",
        timeStyle: "short",
        dateStyle: "short",
      }); //timeZoneName: "short",
      var subject: string;
      var verb: string;
      var object: string;
      var pronoun = shegamers.includes(log.user_id) ? "her" : "his";
      var original: string;
      var result: string;
      var sentence = "";
      switch (log.auth_type) {
        // If player changed their own RSVP, they are the subject and the object is their own pronoun
        case "self":
          subject = playersDict[log.user_id].attrib.given_name;
          object = pronoun;
          break;

        // If admin or host changed a player's RSVP, the admin/host is the subject and the (possessive) player is the object
        default:
          subject = `${playersDict[log.auth_sub].attrib.given_name} (${log.auth_type})`;
          if (playersDict[log.user_id].attrib.given_name.endsWith("s")) {
            object = playersDict[log.user_id].attrib.given_name + "'";
          } else {
            object = playersDict[log.user_id].attrib.given_name + "'s";
          }
          break;
      }

      let originalRsvp = rsvpFinal[log.event_id][log.user_id].originalRsvp;
      switch (log.action) {
        case "delete":
          if (!originalRsvp) rsvpFinal[log.event_id][log.user_id].originalRsvp = log.rsvp;
          verb = "changed";
          original = rsvp;
          result = "undecided";
          rsvpFinal[log.event_id][log.user_id].finalRsvp = "undecided";
          sentence = `${timestamp}: ${subject} ${verb} ${object} RSVP from "${original}" to "${result}"`;
          break;
        case "add":
          if (!originalRsvp) rsvpFinal[log.event_id][log.user_id].originalRsvp = "undecided";
          verb = "marked";
          result = rsvp;
          rsvpFinal[log.event_id][log.user_id].finalRsvp = log.rsvp;
          sentence = `${timestamp}: ${subject} ${verb} ${object} RSVP as "${result}"`;
          break;
        case "update":
          if (!originalRsvp) rsvpFinal[log.event_id][log.user_id].originalRsvp = rsvp_change[log.rsvp];
          verb = "changed";
          original = rsvp_change[log.rsvp].replace("_", " ");
          result = rsvp;
          rsvpFinal[log.event_id][log.user_id].finalRsvp = log.rsvp;
          sentence = `${timestamp}: ${subject} ${verb} ${object} RSVP from "${original}" to "${result}"`;
          break;
      }
      rsvpReadable[event_str].push(sentence);

      originalRsvp = rsvpFinal[log.event_id][log.user_id].originalRsvp;
      let finalRsvp = rsvpFinal[log.event_id][log.user_id].finalRsvp;
      // ( {originalRsvp, finalRsvp} = rsvpFinal[log.event_id][log.user_id])
      if (originalRsvp == "undecided") {
        rsvpFinal[log.event_id][
          log.user_id
        ].finalSentence = `${timestamp}: ${subject} marked ${object} RSVP as "${finalRsvp.replace("_", " ")}"`;
      } else {
        rsvpFinal[log.event_id][
          log.user_id
        ].finalSentence = `${timestamp}: ${subject} changed ${object} RSVP from "${originalRsvp.replace(
          "_",
          " "
        )}" to "${finalRsvp.replace("_", " ")}"`;
      }
    }

    for (const [event_id, eventRsvps] of Object.entries(rsvpFinal)) {
      for (const [user_id, rsvp] of Object.entries(eventRsvps)) {
        let { originalRsvp, finalRsvp } = rsvp;
        if (originalRsvp == finalRsvp) delete rsvpFinal[event_id][user_id];
      }
      if (Object.keys(rsvpFinal[event_id]).length == 0) delete rsvpFinal[event_id];
    }

    if (Object.keys(rsvpFinal).length == 0)
      return { statusCode: 200, body: JSON.stringify({ message: "No new RSVPs" }) };

    // // All changes without reducing to just beginning and end result
    // const rsvpReadable_html: string = Object.entries(rsvpReadable)
    //   .map(([event, sentences]) => {
    //     let _string = `<h3>${event}</h3>`;
    //     const _sentences = sentences.map((sentence) => `<div>${sentence}</div>`).join("");
    //     return _string + _sentences;
    //   })
    //   .join("");

    // Process rsvp_all subscriptions
    const allFormattedEventRsvps = formatEventRsvps(rsvpFinal, eventsDict);
    console.log("primary formatting complete");
    // const rsvp_all_ses = await Promise.allSettled(
    const rsvp_all_promises = email_alert_preferences.rsvp_all.map(
      (user_id) => SendEmail({ toAddresses: [playersDict[user_id].attrib.email], ...allFormattedEventRsvps })
      // // Add rsvpReadable_html above standard final htmlBody
      // {
      //   const { textBody, htmlBody } = allFormattedEventRsvps;
      //   return SendEmail({
      //     toAddresses: [playersDict[user_id].attrib.email],
      //     textBody: textBody,
      //     htmlBody: rsvpReadable_html + "<br><br>" + htmlBody,
      //   });
      // }
    );
    console.log(`rsvp_all_promises count: ${rsvp_all_promises.length}`);

    const rsvp_hosted_promises = email_alert_preferences.rsvp_hosted.map((user_id) => {
      const hostEvents = Object.keys(rsvpFinal).filter((event_id) => eventsDict[event_id].host == user_id);
      if (hostEvents.length > 0) {
        const hostEventRsvps = Object.fromEntries(hostEvents.map((event_id) => [event_id, rsvpFinal[event_id]]));
        return SendEmail({
          toAddresses: [playersDict[user_id].attrib.email],
          ...formatEventRsvps(hostEventRsvps, eventsDict),
        });
      }
    });
    // console.log("%j", { rsvp_hosted_promises: rsvp_hosted_promises });
    console.log(`rsvp_hosted_promises count: ${rsvp_hosted_promises.length}`);
    const sesAllSettled = await Promise.allSettled([...rsvp_hosted_promises, ...rsvp_all_promises]);
    console.log("%j", { sesAllSettled: sesAllSettled });

    return {
      statusCode: 200,
      body: "Success",
    };
  } catch (err) {
    console.error(err);
    return {
      statusCode: 500,
      body: JSON.stringify({
        message: "some error happened",
      }),
    };
  }
};

interface RsvpFinalType {
  [event_id: string]: {
    [user_id: string]: {
      originalRsvp: "attending" | "not_attending" | "undecided" | "";
      finalRsvp: "attending" | "not_attending" | "undecided" | "";
      finalSentence: string;
    };
  };
}
function formatEventRsvps(rsvpFinal: RsvpFinalType, eventsDict: EventDict) {
  const rsvpFinalHtml: string = Object.entries(rsvpFinal)
    .map(([event_id, eventRsvps]) => {
      const event = eventsDict[event_id];
      const event_str = `${event.game} (${formatIsoDate(event.date)})`;
      const _string = `<h3>${event_str}</h3>`;
      const _sentences = Object.entries(eventRsvps)
        .map(([user_id, rsvp]) => {
          return `<div>${rsvp.finalSentence}</div>`;
        })
        .join("");
      return _string + _sentences;
    })
    .join("");

  const rsvpFinalParsed = Object.fromEntries(
    Object.entries(rsvpFinal).map(([event_id, eventRsvps]) => {
      const event = eventsDict[event_id];
      const event_str = `${event.game} (${formatIsoDate(event.date)})`;
      return [event_str, Object.values(eventRsvps).map((rsvp) => rsvp.finalSentence)];
    })
  );

  const rsvpFinalYaml = yaml
    .dump(rsvpFinalParsed, { indent: 2, lineWidth: -1, noCompatMode: true })
    .replaceAll(/''/gm, "'")
    .replaceAll(/(\'$|^\')/gm, "")
    .replaceAll(/':/g, ":")
    .replaceAll(/- '/g, "");

  return { textBody: rsvpFinalYaml, htmlBody: rsvpFinalHtml };
}

function formatIsoDate(isoString: string) {
  return new Date(isoString).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "America/Denver",
  });
}

const shegamers = ["448804a8-3061-704b-87fc-fdda3c123282"];

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
// type EventLogType = Omit<LogType, "event_id" | "user_id" | "rsvp" | "attrib">;
// type PlayerLogType = Omit<LogType, "date" | "previous" | "new" | "event_id" | "rsvp">;

type AllEmailAlertPreferences = {
  rsvp_all: string[];
  rsvp_hosted: string[];
};

type PlayerEmailAlertPreferences = {
  [alert_type in keyof AllEmailAlertPreferences]: boolean;
};

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
  [key: ExistingGameKnightEvent["event_id"]]: ExistingGameKnightEvent | ExistingGameKnightEventDDB;
}

export interface ExistingGameKnightEvent extends GameKnightEvent {
  event_id: string;
}
export interface ExistingGameKnightEventDDB
  extends Omit<GameKnightEvent, "attending" | "not_attending" | "player_pool" | "organizer_pool"> {
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
