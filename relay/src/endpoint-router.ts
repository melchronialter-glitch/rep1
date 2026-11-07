import { randomUUID } from "node:crypto";
import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import WebSocket from "ws";
import { z } from "zod";

const id=z.string().min(1).max(128).regex(/^[A-Za-z0-9._:-]+$/);
export const endpointHelloSchema=z.object({
 type:z.literal("endpoint.hello"),endpointId:id,label:z.string().min(1).max(200),
 kind:z.enum(["chatgpt_thread","ai","laptop","custom"]),
 capabilities:z.object({receive:z.boolean(),send:z.boolean()}).strict(),
}).strict();
export const routedMessageSchema=z.object({
 type:z.literal("route.message"),messageId:z.string().uuid(),conversationId:id,
 from:id,to:z.array(id).max(32),roomId:id.nullable(),text:z.string().min(1).max(16000),
 inReplyTo:z.string().uuid().nullable(),causalParents:z.array(z.string().uuid()).max(32),
 stimulusId:z.string().uuid().nullable(),createdAt:z.string().datetime({offset:true}),
 ttl:z.number().int().min(0).max(16),hops:z.array(id).max(16),
}).strict();
export type RoutedMessage=z.infer<typeof routedMessageSchema>;
type EndpointHello=z.infer<typeof endpointHelloSchema>;
interface Endpoint{hello:EndpointHello;socket:WebSocket;connectedAt:string}
interface Room{roomId:string;members:Set<string>;createdAt:string}
export interface DeliveryResult{message:RoutedMessage;delivered:string[];unavailable:string[]}

export class EndpointRouter{
 private endpoints=new Map<string,Endpoint>();
 private rooms=new Map<string,Room>();
 private messages:RoutedMessage[]=[];
 constructor(private readonly stateFile?:string,private readonly maxMessages=10000){this.load();}

 attach(socket:WebSocket):void{
  let endpointId:string|null=null;
  const timer=setTimeout(()=>socket.close(4008,"endpoint hello timeout"),5000);
  socket.on("message",raw=>{
   try{
    const value=JSON.parse(raw.toString());
    if(!endpointId){
     const hello=endpointHelloSchema.parse(value);const old=this.endpoints.get(hello.endpointId);
     if(old)old.socket.close(4009,"replaced");
     endpointId=hello.endpointId;this.endpoints.set(endpointId,{hello,socket,connectedAt:new Date().toISOString()});
     clearTimeout(timer);socket.send(JSON.stringify({type:"endpoint.accepted",endpointId,rooms:this.roomsFor(endpointId)}));return;
    }
    const ep=this.endpoints.get(endpointId);if(!ep)throw new Error("endpoint not registered");
    if(value?.type==="room.join"){this.join(endpointId,id.parse(value.roomId));socket.send(JSON.stringify({type:"room.joined",roomId:value.roomId}));return;}
    if(value?.type==="room.leave"){this.leave(endpointId,id.parse(value.roomId));socket.send(JSON.stringify({type:"room.left",roomId:value.roomId}));return;}
    if(value?.type==="room.catchup"){const roomId=id.parse(value.roomId);const after=value.afterMessageId?z.string().uuid().parse(value.afterMessageId):null;socket.send(JSON.stringify({type:"room.catchup",roomId,messages:this.catchup(roomId,after,value.limit??200)}));return;}
    if(value?.type!=="route.message")throw new Error("unsupported endpoint message");
    if(!ep.hello.capabilities.send)throw new Error("endpoint is receive-only");
    const parsed=routedMessageSchema.parse(value);if(parsed.from!==endpointId)throw new Error("forged from");
    if(parsed.roomId&&!this.rooms.get(parsed.roomId)?.members.has(endpointId))throw new Error("sender is not a room member");
    const normalized={...parsed,ttl:Math.min(parsed.ttl||8,8),hops:[endpointId]};
    const result=this.route(normalized);
    socket.send(JSON.stringify({type:"route.result",messageId:parsed.messageId,delivered:result.delivered,unavailable:result.unavailable}));
   }catch(error){socket.send(JSON.stringify({type:"endpoint.error",message:error instanceof Error?error.message:"invalid endpoint protocol"}));}
  });
  socket.on("close",()=>{clearTimeout(timer);if(endpointId&&this.endpoints.get(endpointId)?.socket===socket)this.endpoints.delete(endpointId);});
 }

 createRoom(roomId:string,members:string[]=[]){const rid=id.parse(roomId);let room=this.rooms.get(rid);if(!room){room={roomId:rid,members:new Set(),createdAt:new Date().toISOString()};this.rooms.set(rid,room);}for(const m of members)room.members.add(id.parse(m));this.persist();return this.roomView(room);}
 join(endpointId:string,roomId:string){const rid=id.parse(roomId),eid=id.parse(endpointId);let room=this.rooms.get(rid);if(!room)room=this.rooms.set(rid,{roomId:rid,members:new Set(),createdAt:new Date().toISOString()}).get(rid)!;room.members.add(eid);this.persist();return this.roomView(room);}
 leave(endpointId:string,roomId:string){this.rooms.get(id.parse(roomId))?.members.delete(id.parse(endpointId));this.persist();}
 listRooms(){return[...this.rooms.values()].map(r=>this.roomView(r));}
 roomsFor(endpointId:string){return this.listRooms().filter(r=>r.members.includes(endpointId));}
 list(){return[...this.endpoints.values()].map(({hello,connectedAt})=>({...hello,connectedAt,rooms:this.roomsFor(hello.endpointId).map(r=>r.roomId)}));}
 history(conversationId?:string,limit=100){const xs=conversationId?this.messages.filter(x=>x.conversationId===conversationId):this.messages;return xs.slice(-Math.max(1,Math.min(limit,1000)));}
 catchup(roomId:string,afterMessageId:string|null,limit=200){let xs=this.messages.filter(x=>x.roomId===roomId);if(afterMessageId){const i=xs.findIndex(x=>x.messageId===afterMessageId);if(i>=0)xs=xs.slice(i+1);}return xs.slice(-Math.max(1,Math.min(limit,1000)));}

 send(input:{from?:string;to?:string[];roomId?:string|null;conversationId:string;text:string;inReplyTo?:string|null;causalParents?:string[];stimulusId?:string|null}):DeliveryResult{
  const from=input.from??"aster";
  return this.route(routedMessageSchema.parse({type:"route.message",messageId:randomUUID(),conversationId:input.conversationId,from,to:[...new Set(input.to??[])],roomId:input.roomId??null,text:input.text,inReplyTo:input.inReplyTo??null,causalParents:input.causalParents??[],stimulusId:input.stimulusId??null,createdAt:new Date().toISOString(),ttl:8,hops:[from]}));
 }

 inject(input:{roomId:string;conversationId:string;text:string;members?:string[]}){
  const room=this.rooms.get(id.parse(input.roomId));if(!room)throw new Error("room not found");
  const stimulusId=randomUUID();const targets=input.members?.map(id.parse)??[...room.members];
  const results=targets.map(target=>this.send({from:"experiment",to:[target],roomId:null,conversationId:input.conversationId,text:input.text,stimulusId}));
  return{stimulusId,targets,results};
 }

 private route(message:RoutedMessage):DeliveryResult{
  if(this.messages.some(x=>x.messageId===message.messageId))return{message,delivered:[],unavailable:[]};
  this.messages.push(message);if(this.messages.length>this.maxMessages)this.messages.splice(0,this.messages.length-this.maxMessages);this.persist();
  let targets=[...message.to];
  if(message.roomId){const room=this.rooms.get(message.roomId);if(!room)throw new Error("room not found");targets=[...new Set([...targets,...room.members])].filter(x=>x!==message.from);}
  const delivered:string[]=[],unavailable:string[]=[];if(message.ttl<=0)return{message,delivered,unavailable:targets};
  for(const target of targets){if(message.hops.includes(target))continue;const ep=this.endpoints.get(target);if(!ep||!ep.hello.capabilities.receive||ep.socket.readyState!==WebSocket.OPEN){unavailable.push(target);continue;}ep.socket.send(JSON.stringify({...message,ttl:message.ttl-1,hops:[...message.hops,"aster-router"]}));delivered.push(target);}
  return{message,delivered,unavailable};
 }
 private roomView(r:Room){return{roomId:r.roomId,members:[...r.members],createdAt:r.createdAt};}
 private persist(){if(!this.stateFile)return;mkdirSync(dirname(this.stateFile),{recursive:true});const tmp=this.stateFile+".tmp";writeFileSync(tmp,JSON.stringify({rooms:this.listRooms(),messages:this.messages},null,2),"utf8");renameSync(tmp,this.stateFile);}
 private load(){if(!this.stateFile)return;try{const x=JSON.parse(readFileSync(this.stateFile,"utf8"));for(const r of x.rooms??[])this.rooms.set(id.parse(r.roomId),{roomId:r.roomId,members:new Set((r.members??[]).map((m:unknown)=>id.parse(m))),createdAt:r.createdAt});for(const m of x.messages??[])this.messages.push(routedMessageSchema.parse(m));}catch(error:any){if(error?.code!=="ENOENT")throw error;}}
 close(){for(const e of this.endpoints.values())e.socket.close(1001,"router stopped");this.endpoints.clear();}
}
