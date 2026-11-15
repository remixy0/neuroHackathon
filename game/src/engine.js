export const DURATION = 90;
export const LANE_WIDTH = 2.4;
export function rng(seed) { return () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
export function createTrack(seed) {
 const random=rng(seed), items=[];
 for(let z=25;z<1800;z+=16+random()*8){
  const lane=Math.floor(random()*3)-1, type=['block','barrier','gate'][Math.floor(random()*3)];
  items.push({z,lane,type});
  const safe=(lane+2)%3-1;
  for(let j=0;j<4;j++)items.push({z:z+2+j*2,lane:safe,type:'coin'});
 }
 return items;
}
export function createPlayer(){ return {lane:0,x:0,distance:0,lives:3,coins:0,score:0,jump:0,slide:0,invulnerable:0,alive:true,seen:new Set()}; }
export function command(p,direction){
 if(!p.alive)return;
 if(direction==='left')p.lane=Math.max(-1,p.lane-1);
 if(direction==='right')p.lane=Math.min(1,p.lane+1);
 if(direction==='up'&&p.jump<=0&&p.slide<=0)p.jump=.95;
 if(direction==='down'&&p.jump<=0&&p.slide<=0)p.slide=.95;
}
export function jumpHeight(p){return p.jump>0?Math.sin((1-p.jump/.95)*Math.PI)*2.5:0;}
export function advance(p,dt,speed,track){
 if(!p.alive)return [];
 p.distance+=speed*dt;p.x+=(p.lane*LANE_WIDTH-p.x)*Math.min(1,dt*14);
 p.jump=Math.max(0,p.jump-dt);p.slide=Math.max(0,p.slide-dt);p.invulnerable=Math.max(0,p.invulnerable-dt);
 const events=[];
 track.forEach((item,i)=>{
  if(p.seen.has(i)||item.z>p.distance+.6)return;
  p.seen.add(i);
  if(Math.abs(p.x-item.lane*LANE_WIDTH)>1)return;
  if(item.type==='coin'){p.coins++;events.push('coin');return;}
  const safe=item.type==='barrier'&&jumpHeight(p)>1.05 || item.type==='gate'&&p.slide>0;
  if(!safe&&p.invulnerable<=0){p.lives--;p.invulnerable=1.8;events.push('hit');if(p.lives<=0){p.alive=false;events.push('out');}}
 });
 p.score=Math.floor(p.distance*10)+p.coins*25;
 return events;
}
export function parseInput(raw){
 try{
  const data=typeof raw==='string'?JSON.parse(raw):raw;
  if(!data||![1,2].includes(data.player))return null;
  const aliases={left:'left',right:'right',up:'up',down:'down',lewo:'left',prawo:'right',gora:'up','góra':'up',dol:'down','dół':'down'};
  const direction=aliases[data.direction];
  if(!direction||Object.hasOwn(data,'type')&&data.type!=='input')return null;
  return {player:data.player-1,direction,id:data.id};
 }catch{return null;}
}
