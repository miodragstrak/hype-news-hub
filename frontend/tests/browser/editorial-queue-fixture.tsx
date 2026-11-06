/** Browser fixture only; never imported by either production entry point. */
import React from "react";
import { createRoot } from "react-dom/client";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import App from "../../src/App";
import { DemoDataProvider } from "../../src/context/DemoDataContext";
import type { PrivateQueueStory } from "../../src/types/editorialQueue";
import { TestEditorialIdentity, uuid } from "../editorialFixtures";
import { editorial } from "../fixtures";
import "../../src/index.css";

const identity = new TestEditorialIdentity();
const calls: {path:string;method:string}[]=[];
let error=0;
const rows: PrivateQueueStory[] = Array.from({length:23},(_,index)=>({...editorial,id:uuid(index+1),
  headline:index ? `Privatna vest ${index+1}` : "Dugačka vest "+"X".repeat(500),
  editorial: null, ai:index ? {has_suggestion:false,latest_suggestion_id:null,status:null,created_at:null,completed_at:null,recovery_required:false}
    :{has_suggestion:true,latest_suggestion_id:uuid(901),status:"processing",created_at:"2026-11-06T09:00:00Z",completed_at:null,recovery_required:true}}));
const json=(value:unknown,status=200)=>Promise.resolve(new Response(JSON.stringify(value),{status}));
window.fetch=async(input,init={})=>{
  const url=new URL(String(input),location.href),path=url.pathname;calls.push({path,method:init.method??"GET"});
  if(path.endsWith('/capabilities'))return json({roles:['reader'],permissions:['editorial:read'],storage:'postgres',commands_enabled:false});
  if(path==='/api/editorial/queue'){
    if(error)return json({detail:'SENSITIVE INTERNAL DETAILS'},error);
    const limit=Number(url.searchParams.get('limit')),offset=Number(url.searchParams.get('offset')),stories=rows.slice(offset,offset+limit);
    return json({stories,stories_total:rows.length,limit,offset,has_more:offset+stories.length<rows.length});
  }
  if(path==='/api/discovery')return json([]);
  if(path==='/api/stories')return json({stories:[],stories_total:0});
  if(path==='/api/editorial-queue')return json({stories:[{...editorial,headline:'PUBLIC FALLBACK MUST NOT APPEAR'}],stories_total:1});
  throw Error('Unexpected browser fixture request');
};
Object.assign(window,{queueFixture:{calls,fail:(status:number)=>{error=status;},logout:()=>identity.changeSession(null)}});
const router=createMemoryRouter([{path:'*',element:<App editorialIdentity={identity}/>}],{initialEntries:['/review']});
createRoot(document.getElementById('root')!).render(<React.StrictMode><DemoDataProvider><RouterProvider router={router}/></DemoDataProvider></React.StrictMode>);
