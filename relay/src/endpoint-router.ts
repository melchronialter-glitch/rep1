import { randomUUID } from "node:crypto";
import WebSocket from "ws";
import { z } from "zod";

const id=z.string().min(1).max(128).regex(/^[A-Za-z0-9._:-]+$/);
export const endpointHelloSchema=z.object({
 type:z.literal("endpoint.hello"), endpointId:id, label:z.string().min(1).max(200),
 kind:z.enum(["chatgpt_thread","ai","laptop","custom"]),
 capabilities:z.object({receive:z.boolean(),send:z.boolean()}).strict(),
}).strict();
export const routedMessageSchema=z.object({
 type:z.literal("route.message"), messageId:z.string().uuid(), conversationId:id,
 from:id,to:z.array(id).min(1).max(32),text:z.string().min(1).max(16000),
 inReplyTo:z.string().uuid().nullable(),createdAt:z.string().datetime({offset:true}),
 ttl:z.number().int().min(0).max(16),hops:z.array(id).max(16),
}).strict();
export type RoutedMessage=z.infer<typeof routedMessageSchema>;
type EndpointHello=z.infer<typeof endpointHelloSchema>;
interface Endpoint{hello:EndpointHello;socket:WebSocket;connectedAt:string}
export interface DeliveryResult{message:RoutedMessage;delivered:string[];unavailable:string[]}

export class EndpointRouter{
 private endpoints=new Map<string,Endpoint>();
 private messages:RoutedMessage[]=[];
 constructor(private readonly maxMessages=2000){}

 attach(socket:WebSocket):void{
  let endpointId:string|null=null;
  const timer=setTimeout(()=>socket.close(4008,"endpoint hello timeout"),5000);
  socket.on("message",raw=>{
   try{
    const value=JSON.parse(raw.toString());
    if(!endpointId){
     const hello=endpointHelloSchema.parse(value);
     const old=this.endpoints.get(hello.endpointId); if(old) old.socket.close(4009,"replaced");
     endpointId=hello.endpointId; this.endpoints.set(endpointId,{hello,socket,connectedAt:new Date().toISOString()});
     clearTimeout(timer); socket.send(JSON.stringify({type:"endpoint.accepted",endpointId})); return;
    }
    if(value?.type!=="route.message") throw new Error("unsupported endpoint message");
    const ep=this.endpoints.get(endpointId); if(!ep?.hello.capabilities.send) throw new Error("endpoint is receive-only");
    const parsed=routedMessageSchema.parse(value);
    if(parsed.from!==endpointId) throw new Error("forged from");
    // The router owns routing metadata. Endpoints cannot pre-populate hops or claim arbitrary TTL state.
    const normalized:{[K in keyof RoutedMessage]:RoutedMessage[K]}={...parsed,ttl:Math.min(parsed.ttl||8,8),hops:[endpointId]};
    const result=this.route(normalized);
    socket.send(JSON.stringify({type:"route.result",messageId:parsed.messageId,delivered:result.delivered,unavailable:result.unavailable}));
   }catch(error){socket.send(JSON.stringify({type:"endpoint.error",message:error instanceof Error?error.message:"invalid endpoint protocol"}));}
  });
  socket.on("close",()=>{clearTimeout(timer);if(endpointId&&this.endpoints.get(endpointId)?.socket===socket)this.endpoints.delete(endpointId);});
 }
 list(){return [...this.endpoints.values()].map(({hello,connectedAt})=>({...hello,connectedAt}));}
 history(conversationId?:string,limit=100){const xs=conversationId?this.messages.filter(x=>x.conversationId===conversationId):this.messages;return xs.slice(-Math.max(1,Math.min(limit,500)));}
 send(input:{from?:string;to:string[];conversationId:string;text:string;inReplyTo?:string|null}):DeliveryResult{
  const from=input.from??"aster";
  return this.route(routedMessageSchema.parse({type:"route.message",messageId:randomUUID(),conversationId:input.conversationId,from,to:[...new Set(input.to)],text:input.text,inReplyTo:input.inReplyTo??null,createdAt:new Date().toISOString(),ttl:8,hops:[from]}));
 }
 private route(message:RoutedMessage):DeliveryResult{
  if(this.messages.some(x=>x.messageId===message.messageId))return{message,delivered:[],unavailable:message.to};
  this.messages.push(message);if(this.messages.length>this.maxMessages)this.messages.splice(0,this.messages.length-this.maxMessages);
  const delivered:string[]=[],unavailable:string[]=[];
  if(message.ttl<=0)return{message,delivered,unavailable:[...message.to]};
  for(const target of message.to){
   const ep=this.endpoints.get(target);
   if(!ep||!ep.hello.capabilities.receive||ep.socket.readyState!==WebSocket.OPEN){unavailable.push(target);continue;}
   const outbound={...message,ttl:message.ttl-1,hops:[...message.hops,"aster-router"]};
   ep.socket.send(JSON.stringify(outbound));delivered.push(target);
  }
  return{message,delivered,unavailable};
 }
 close(){for(const e of this.endpoints.values())e.socket.close(1001,"router stopped");this.endpoints.clear();}
}
