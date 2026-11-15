import {WebSocketServer} from 'ws';
import readline from 'node:readline';
const wss=new WebSocketServer({host:'127.0.0.1',port:8765});
console.log('WebSocket: ws://localhost:8765\nWpisz np. 1 left lub 2 up i Enter. Ctrl+C kończy.');
wss.on('connection',()=>console.log('Gra połączona.'));
let id=0;
readline.createInterface({input:process.stdin}).on('line',line=>{const [p,direction]=line.trim().split(/\s+/);const player=Number(p);if(![1,2].includes(player)||!['left','right','up','down'].includes(direction)){console.log('Format: 1 left | 2 right | 1 up | 2 down');return;}const message=JSON.stringify({type:'input',player,direction,id:++id});for(const client of wss.clients)if(client.readyState===1)client.send(message);});
wss.on('error',error=>{console.error(error.message);process.exitCode=1;});
