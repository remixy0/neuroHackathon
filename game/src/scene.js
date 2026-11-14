import * as THREE from 'three'
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js'
import { LANE_WIDTH, jumpHeight, rng } from './engine.js'

// Shared geometry and a three-band ramp keep both views light and consistently illustrated.
const ramp = new THREE.DataTexture(new Uint8Array([105,105,105,255,195,195,195,255,255,255,255,255]), 3, 1, THREE.RGBAFormat)
ramp.minFilter = ramp.magFilter = THREE.NearestFilter
ramp.needsUpdate = true
const materials = new Map()
function material(color) {
    if (!materials.has(color)) materials.set(color, new THREE.MeshToonMaterial({color, gradientMap:ramp}))
    return materials.get(color)
}
const cube = new THREE.BoxGeometry(1,1,1)
const rounded = new RoundedBoxGeometry(1,1,1,2,.14)
const sphere = new THREE.SphereGeometry(1,16,12)
const coinGeometry = new THREE.CylinderGeometry(.31,.31,.12,16)
function shape(parent,geometry,color,x,y,z,w,h,d) {
    const mesh=new THREE.Mesh(geometry,material(color))
    mesh.position.set(x,y,z); mesh.scale.set(w,h,d)
    mesh.castShadow=true; mesh.receiveShadow=true; parent.add(mesh); return mesh
}
const box=(p,c,x,y,z,w,h,d)=>shape(p,cube,c,x,y,z,w,h,d)
const soft=(p,c,x,y,z,w,h,d)=>shape(p,rounded,c,x,y,z,w,h,d)
const ball=(p,c,x,y,z,w,h,d)=>shape(p,sphere,c,x,y,z,w,h,d)
const cream=0xfff4d6, ink=0x34465c

export class View {
    constructor(canvas,accent,seed) {
        this.canvas=canvas; this.accent=accent
        this.renderer=new THREE.WebGLRenderer({canvas,antialias:true,powerPreference:'high-performance'})
        this.renderer.setPixelRatio(Math.min(devicePixelRatio,1.6))
        this.renderer.shadowMap.enabled=true; this.renderer.shadowMap.type=THREE.PCFSoftShadowMap
        this.renderer.outputColorSpace=THREE.SRGBColorSpace
        this.scene=new THREE.Scene(); this.scene.background=new THREE.Color(0xa8dff1)
        this.scene.fog=new THREE.Fog(0xa8dff1,45,130)
        this.camera=new THREE.PerspectiveCamera(53,1,.1,220)
        this.camera.position.set(0,6.3,9.5); this.camera.lookAt(0,1,-16)
        this.scene.add(new THREE.HemisphereLight(0xffffff,0x94bca0,2.1))
        const sun=new THREE.DirectionalLight(0xfff1ce,2.4)
        sun.position.set(-18,30,12); sun.castShadow=true; sun.shadow.mapSize.set(1024,1024)
        Object.assign(sun.shadow.camera,{left:-18,right:18,top:30,bottom:-25})
        sun.shadow.normalBias=.04; this.scene.add(sun)
        box(this.scene,0x9dcf79,0,-.55,-55,100,.5,160)
        box(this.scene,0xd9bd96,0,-.25,-55,8.4,.5,150)
        for(const x of [-5.2,5.2])box(this.scene,0xffe5ba,x,-.05,-55,2,.35,150)
        for(const x of [-4.15,4.15])box(this.scene,cream,x,.12,-55,.16,.22,150)
        for(const x of [-1.2,1.2])box(this.scene,cream,x,.015,-55,.065,.02,150)
        this.markers=new THREE.Group(); this.scene.add(this.markers)
        for(let i=0;i<45;i++)for(const x of [-2.4,0,2.4])box(this.markers,0xcba982,x,.025,-i*4,1.9,.025,.055)

        this.city=new THREE.Group(); this.scene.add(this.city)
        const random=rng(seed), palette=[0xffb46e,0x80c4c2,0xf0a4b1,0xb5b1dc,0xffd879]
        for(let i=0;i<34;i++) {
            const side=i%2?1:-1, g=new THREE.Group(), h=3+random()*3.8,w=3+random()*1.5
            g.position.x=side*(8+random()*2); this.city.add(g)
            soft(g,palette[i%5],0,h/2,0,w,h,4.8)
            soft(g,cream,0,h+.05,0,w+.35,.3,5.1)
            soft(g,0xe57861,0,h+.34,0,w+.15,.35,4.9)
            for(let y=1.4;y<h-.4;y+=1.6)for(const x of [-w*.23,w*.23]) {
                soft(g,cream,x,y,2.43,.9,1.15,.12)
                soft(g,0x4a829b,x,y,2.51,.65,.86,.08)
                box(g,cream,x,y,2.56,.055,.85,.025)
            }
            soft(g,0x599095,0,.72,2.46,.85,1.4,.15)
            // Candy-striped shop awning, repeated in coherent little streets.
            for(let j=0;j<6;j++) {
                const awning=soft(g,j%2?cream:0xe97463,(j-2.5)*w/6,2,2.8,w/6,.16,.9)
                awning.rotation.x=.15
            }
            const tx=-side*(w*.5+1.1)
            soft(g,0xa77a50,tx,1,0,.22,2,.22)
            ball(g,0x59ad72,tx,2.35,0,1.1,1.3,1.1)
            ball(g,0x88c966,tx-.4,2.75,.1,.8,.9,.8)
            soft(g,0xf2c78d,tx,.16,0,1,.35,1)
            for(const z of [-2.9,2.9]) {
                soft(g,0x6caa70,-side*(w*.5+.4),.34,z,.8,.6,1.3)
                ball(g,0xffdf76,-side*(w*.5+.4),.7,z,.12,.12,.12)
            }
        }
        this.arches=new THREE.Group(); this.scene.add(this.arches)
        const flagGeometry=new THREE.ConeGeometry(.32,.65,3)
        for(let i=0;i<5;i++) {
            const g=new THREE.Group();this.arches.add(g)
            for(const x of [-4.8,4.8]) {
                soft(g,0xe8c38b,x,2.8,0,.16,5.6,.16)
                ball(g,cream,x,5.65,0,.16,.16,.16)
            }
            box(g,0x97785c,0,5.4,0,9.6,.035,.035)
            for(let j=0;j<11;j++) {
                const flag=new THREE.Mesh(flagGeometry,material(palette[j%5]))
                flag.rotation.z=Math.PI; flag.position.set((j-5)*.8,5.1,0);g.add(flag)
            }
        }
        ball(this.scene,0xffedac,-23,32,-110,5,5,2)
        for(let i=0;i<9;i++) {
            const x=(i-4)*12,y=15+(i%3)*4,z=-65-(i%2)*30
            for(let j=0;j<3;j++)ball(this.scene,0xfffdf3,x+(j-1)*2.3,y+(j===1?1:0),z,2.8,1.4+(j===1?.5:0),1.5)
        }
        this.runner=new THREE.Group();this.scene.add(this.runner)
        this.body=new THREE.Group();this.runner.add(this.body)
        // Oversized helmet, mittens and sneakers give the runners toy-like proportions.
        soft(this.body,accent,0,1.05,0,.82,.85,.6)
        soft(this.body,ink,0,.65,0,.68,.27,.5)
        ball(this.body,0xffd3aa,0,1.83,0,.46,.47,.41)
        ball(this.body,accent,0,2.04,.01,.51,.37,.46)
        soft(this.body,cream,0,2.19,.36,.17,.32,.08)
        soft(this.body,accent,0,1.96,-.43,.7,.09,.4)
        for(const x of [-.16,.16])ball(this.body,ink,x,1.83,-.38,.045,.07,.035)
        for(const x of [-.46,.46])ball(this.body,0xffd3aa,x,1.79,0,.11,.14,.13)
        soft(this.body,0xf6b94d,0,1.08,.39,.59,.65,.3)
        soft(this.body,0xffdf81,0,.98,.57,.43,.27,.1)
        soft(this.body,cream,0,1.27,.57,.14,.14,.025)
        this.legs=[];this.arms=[]
        for(const side of [-1,1]) {
            const leg=new THREE.Group();leg.position.set(side*.22,.66,0);this.body.add(leg)
            soft(leg,ink,0,-.22,0,.29,.5,.32)
            soft(leg,cream,0,-.49,-.1,.38,.25,.6)
            soft(leg,accent,0,-.45,-.1,.39,.11,.4)
            this.legs.push(leg)
            const arm=new THREE.Group();arm.position.set(side*.5,1.35,0);arm.rotation.z=side*.12;this.body.add(arm)
            soft(arm,accent,0,-.19,0,.28,.44,.3)
            ball(arm,cream,0,-.45,0,.18,.2,.17);this.arms.push(arm)
        }
        this.objects=new Map();this.track=[]
        this.resizeObserver=new ResizeObserver(()=>this.resize());this.resizeObserver.observe(canvas.parentElement);this.resize()
    }
    resize(){const {width,height}=this.canvas.getBoundingClientRect();if(!width||!height)return;this.renderer.setSize(width,height,false);this.camera.aspect=width/height;this.camera.updateProjectionMatrix()}
    reset(track){for(const o of this.objects.values())this.scene.remove(o);this.objects.clear();this.track=track}
    make(item){
        const g=new THREE.Group();g.position.x=item.lane*LANE_WIDTH
        if(item.type==='coin') {
            const coin=new THREE.Mesh(coinGeometry,material(0xffcb38));coin.rotation.x=Math.PI/2
            const spin=new THREE.Group();spin.position.y=1;spin.add(coin)
            soft(spin,0xffef9e,0,0,.07,.075,.34,.03);g.add(spin)
        }
        if(item.type==='block') {
            soft(g,0xf28c65,0,1.45,0,1.95,2.9,4)
            soft(g,cream,0,2.87,0,2,.28,4.1)
            soft(g,cream,0,2.1,2.01,1.65,.93,.12)
            soft(g,0x437f99,0,2.1,2.09,1.4,.67,.08)
            box(g,cream,0,2.1,2.15,.08,.7,.02)
            soft(g,0xa65844,0,.55,2.06,1.6,.25,.18)
            for(const x of [-.64,.64])ball(g,0xffedac,x,1.15,2.04,.18,.18,.09)
            for(const x of [-.96,.96])for(const z of [-1.2,1.2])ball(g,ink,x,.33,z,.16,.33,.33)
            for(const x of [-.99,.99])for(const z of [-1.05,.1,1.2])soft(g,0x437f99,x,2,z,.05,.65,.8)
        }
        if(item.type==='barrier') {
            soft(g,0xf39255,0,.55,0,1.95,1.1,.45)
            for(let i=-2;i<=2;i++){const stripe=box(g,cream,i*.36,.55,.24,.17,.82,.025);stripe.rotation.z=-.4}
            for(const x of [-.73,.73])soft(g,0xb16c46,x,.12,0,.3,.24,.7)
        }
        if(item.type==='gate') {
            for(const x of [-.9,.9])soft(g,0x8d75ba,x,1.5,0,.18,3,.35)
            soft(g,0xa393d2,0,2.22,0,1.95,1.1,.5)
            soft(g,cream,0,2.22,.27,.65,.7,.04)
            // Arrow points down: duck under this obstacle.
            box(g,0x8065b0,0,2.3,.3,.09,.3,.025)
            for(const side of [-1,1]){const line=box(g,0x8065b0,side*.085,2.17,.3,.08,.24,.025);line.rotation.z=-side*.7}
        }
        this.scene.add(g);return g
    }
    render(p,time) {
        this.markers.position.z=p.distance%4
        this.city.children.forEach((b,i)=>{b.position.z=12-((Math.floor(i/2)*9-p.distance%153+153)%153)})
        this.arches.children.forEach((b,i)=>{b.position.z=10-((i*30-p.distance%150+150)%150)})
        this.track.forEach((item,i)=>{
            const z=p.distance-item.z
            if(z < -105||z>9||(p.seen.has(i)&&item.type==='coin')){if(this.objects.has(i)){this.scene.remove(this.objects.get(i));this.objects.delete(i)}return}
            let obj=this.objects.get(i);if(!obj){obj=this.make(item);this.objects.set(i,obj)}obj.position.z=z
            if(item.type==='coin')obj.children[0].rotation.y=time*3
        })
        this.runner.position.set(p.x,jumpHeight(p),0)
        this.runner.visible=p.alive&&!(p.invulnerable>0&&Math.floor(time*12)%2)
        this.body.scale.set(p.slide>0?1.12:1,p.slide>0?.42:1,p.slide>0?1.3:1)
        this.body.rotation.z=(p.lane*LANE_WIDTH-p.x)*-.13
        const stride=p.alive&&p.jump<=0&&p.slide<=0?Math.sin(time*17)*.65:0
        this.legs.forEach((l,i)=>l.rotation.x=stride*(i?1:-1));this.arms.forEach((l,i)=>l.rotation.x=stride*(i?-1:1))
        this.renderer.render(this.scene,this.camera)
    }
}
