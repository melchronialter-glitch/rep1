import assert from "node:assert/strict";
import test from "node:test";
import WebSocket from "ws";
import { EndpointRouter } from "../src/endpoint-router.js";

function fakeSocket(){
 const sent:string[]=[];
 const handlers=new Map<string,Function[]>();
 const s:any={readyState:WebSocket.OPEN,send:(x:string)=>sent.push(x),close:()=>{},on:(n:string,f:Function)=>handlers.set(n,[...(handlers.get(n)??[]),f])};
 return {socket:s as WebSocket,sent,emit:(n:string,x?:unknown)=>{for(const f of handlers.get(n)??[])f(x);}};
}
test("router preserves distinct endpoint identity and reports unavailable targets",()=>{
 const r=new EndpointRouter(); const a=fakeSocket(),b=fakeSocket();
 r.attach(a.socket);r.attach(b.socket);
 a.emit("message",Buffer.from(JSON.stringify({type:"endpoint.hello",endpointId:"a",label:"A",kind:"ai",capabilities:{receive:true,send:true}})));
 b.emit("message",Buffer.from(JSON.stringify({type:"endpoint.hello",endpointId:"b",label:"B",kind:"ai",capabilities:{receive:true,send:true}})));
 a.emit("message",Buffer.from(JSON.stringify({type:"route.message",messageId:"00000000-0000-4000-8000-000000000001",conversationId:"c",from:"a",to:["b","missing"],text:"x",inReplyTo:null,createdAt:new Date().toISOString(),ttl:8,hops:[]})));
 const delivered=JSON.parse(b.sent.at(-1)!); assert.equal(delivered.from,"a");assert.deepEqual(delivered.hops,["a","aster-router"]);
 const result=JSON.parse(a.sent.at(-1)!);assert.deepEqual(result.delivered,["b"]);assert.deepEqual(result.unavailable,["missing"]);
});
test("receive-only endpoint cannot send",()=>{
 const r=new EndpointRouter();const a=fakeSocket();r.attach(a.socket);
 a.emit("message",Buffer.from(JSON.stringify({type:"endpoint.hello",endpointId:"a",label:"A",kind:"ai",capabilities:{receive:true,send:false}})));
 a.emit("message",Buffer.from(JSON.stringify({type:"route.message",messageId:"00000000-0000-4000-8000-000000000002",conversationId:"c",from:"a",to:["x"],text:"x",inReplyTo:null,createdAt:new Date().toISOString(),ttl:8,hops:[]})));
 assert.match(JSON.parse(a.sent.at(-1)!).message,/receive-only/);
});
