// Local WebGL2 level viewer. Mesh buffers are shared by all authored instances.
window.createLevelViewer=async function(container,id,signal){
 const node=(tag,text)=>{const n=document.createElement(tag);if(text)n.textContent=text;return n;};
 const status=node('p','Assembling level geometry and placements...');status.setAttribute('role','status');container.append(status);
 const get=async(url,binary=false)=>{const r=await fetch(url,{signal});if(!r.ok)throw Error(await r.text());return binary?r.arrayBuffer():r.json();};
 const scene=await get(`/asset/${id}/level`);if(signal.aborted)return;if(scene.version!==2||scene.vertexStride!==48)throw Error('Level format changed. Restart the viewer server and refresh this page.');
 status.textContent='Loading shared geometry...';const bytes=await get(`/asset/${id}/level-bin`,true);if(signal.aborted)return;
 const toolbar=node('div'),layers=node('div'),canvas=node('canvas'),help=node('p'),details=node('details'),summary=node('summary','Assembly details');
 toolbar.className=layers.className='model-controls';canvas.className='level-canvas';canvas.tabIndex=0;canvas.setAttribute('aria-label','3D level fly-through. Drag to look; W A S D to fly; Space to ascend; Control to descend along the Y axis.');
 help.textContent='Drag to look | W A S D: fly | Space: up | Ctrl: down | Shift: faster | Scroll: flight speed | Click the view to use keys';
 const report=node('pre');report.textContent=JSON.stringify({report:scene.report,warnings:scene.warnings},null,2);details.append(summary,report);
 const note=node('p','Saved geometry, vertex colors, static lighting, fog volumes, water tiling and base-layer material blending. Runtime lights, shadows, water effects, secondary material layers, moving objects and spawns are not fully reproduced. Missing references are listed in Assembly details.');note.className='note';container.replaceChildren(toolbar,layers,canvas,help,status,note,details);
 const gl=canvas.getContext('webgl2',{antialias:true,alpha:false});if(!gl)throw Error('This level viewer requires WebGL 2.');
 const shaders=[];function shader(type,source){const s=gl.createShader(type);shaders.push(s);gl.shaderSource(s,source);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(s));return s;}
 const program=gl.createProgram();gl.attachShader(program,shader(gl.VERTEX_SHADER,`#version 300 es
 layout(location=0) in vec3 position;layout(location=1) in vec3 normal;layout(location=2) in vec2 uv;layout(location=3) in vec4 color;
 uniform mat4 vp;uniform mat4 world;uniform vec2 fogCurve;uniform bool fogEnabled;out float fogAmount;out vec3 n;out vec2 tex;out vec4 col;
 void main(){gl_Position=vp*world*vec4(position,1.);mat3 basis=mat3(world);n=abs(determinant(basis))>.00000001?transpose(inverse(basis))*normal:normal;tex=uv;col=color;fogAmount=fogEnabled?1.-clamp((fogCurve.x+fogCurve.y/max(gl_Position.w,.0001))/255.,0.,1.):0.;}`));
 gl.attachShader(program,shader(gl.FRAGMENT_SHADER,`#version 300 es
 precision highp float;in float fogAmount;uniform vec3 fogColor;uniform float alphaCutoff;in vec3 n;in vec2 tex;in vec4 col;uniform vec3 ambient;uniform vec3 lightColor[3];uniform vec3 lightDirection[3];uniform bool vertexColors;uniform bool baked;uniform sampler2D image;uniform bool textured;uniform bool unlit;uniform vec4 tint;out vec4 frag;
 void main(){vec4 c=textured?texture(image,tex):vec4(1.);c*=tint;if(vertexColors)c.rgb*=col.rgb;c.a*=col.a;if(c.a<=alphaCutoff)discard;vec3 light=vec3(1.);if(!unlit&&!baked){light=ambient;vec3 normal=n/max(length(n),.00001);for(int i=0;i<3;i++)light+=lightColor[i]*max(0.,dot(normal,lightDirection[i]));}frag=vec4(mix(c.rgb*light,fogColor,fogAmount),c.a);}`));
 gl.linkProgram(program);if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(program));gl.useProgram(program);
 const u=Object.fromEntries(['vp','world','image','textured','unlit','tint','vertexColors','baked','ambient','lightColor[0]','lightDirection[0]','fogCurve','fogEnabled','fogColor','alphaCutoff'].map(k=>[k,gl.getUniformLocation(program,k)]));
 const vb=gl.createBuffer(),ib=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,vb);gl.bufferData(gl.ARRAY_BUFFER,bytes,gl.STATIC_DRAW);gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,ib);gl.bufferData(gl.ELEMENT_ARRAY_BUFFER,bytes,gl.STATIC_DRAW);for(let i=0;i<4;i++)gl.enableVertexAttribArray(i);
 const textures=new Map(),enabled=new Set(Object.keys(scene.groups).filter(k=>k!=='Inactive / templates'));
 let disposed=false,raf=0,last=0,yaw=0,pitch=-.4,eye=[0,0,0],speed=10,unlit=false,textured=true,vertexColors=true,fogEnabled=true,drag=null;
 const keys=new Set(),min=scene.bounds[0],max=scene.bounds[1],center=min.map((v,i)=>(v+max[i])/2),radius=Math.max(1,Math.hypot(...max.map((v,i)=>(v-min[i])/2)));
 const multiply=(a,b)=>{const out=new Float32Array(16);for(let c=0;c<4;c++)for(let r=0;r<4;r++)for(let k=0;k<4;k++)out[c*4+r]+=a[k*4+r]*b[c*4+k];return out;};
 const transform=(m,p)=>p.map((_,k)=>m[k]*p[0]+m[4+k]*p[1]+m[8+k]*p[2]+m[12+k]);
 const placed=scene.nodes.flatMap(n=>n.water?Array.from({length:36},(_,i)=>({...n,waterTile:[Math.floor(i/6)-3,i%6-3]})):[n]);
 const draws=placed.map(n=>{const selected=n.lights||scene.lights||[],ambient=n.ambient||scene.ambient||[1,1,1],direct=selected.filter(l=>l.type==='directional').slice(0,3),lightColors=new Float32Array(9),lightDirections=new Float32Array(9);direct.forEach((l,i)=>{lightColors.set(l.color,i*3);lightDirections.set(l.direction,i*3);});if(!n.lights){const points=(scene.pointLights||[]).map(l=>{const delta=l.position.map((v,i)=>v-n.matrix[12+i]),distance=Math.hypot(...delta);return {direction:delta.map(v=>v/(distance+.1)),color:l.color.map(v=>Math.min(1,v*l.radius/(distance+.1))),distance,radius:l.radius};}).filter(l=>l.distance<l.radius*5).sort((a,b)=>Math.max(...b.color)-Math.max(...a.color));points.slice(0,Math.max(0,3-direct.length)).forEach((l,i)=>{lightColors.set(l.color,(direct.length+i)*3);lightDirections.set(l.direction,(direct.length+i)*3);});}const g=scene.geometry[n.modelId],m=n.matrix,c=g.bounds[0].map((v,i)=>(v+g.bounds[1][i])/2),r=Math.hypot(...g.bounds[1].map((v,i)=>(v-g.bounds[0][i])/2));return {...n,ambient,lightColors,lightDirections,world:new Float32Array(m),geometry:g,center:transform(m,c),radius:r*Math.max(...[0,4,8].map(i=>Math.hypot(m[i],m[i+1],m[i+2])))};});
 function schedule(){if(!disposed&&!raf)raf=requestAnimationFrame(draw);}
 function aim(target,r){eye=[target[0]+r*.7,target[1]+r*.6,target[2]+r*.9];const d=target.map((v,i)=>v-eye[i]);yaw=Math.atan2(d[0],-d[2]);pitch=Math.atan2(d[1],Math.hypot(d[0],d[2]));schedule();}
 function button(text,fn){const b=node('button',text);b.onclick=fn;toolbar.append(b);return b;}
 button('Overview',()=>aim(center,radius));button('Ground view',()=>{const target=draws.find(n=>n.source==='BOG moby')?.center||center;eye=[target[0],target[1]+2,target[2]+5];pitch=0;schedule();canvas.focus();});
 const speedLabel=node('span');function setSpeed(v){speed=Math.min(2000,Math.max(.1,v));speedLabel.textContent=`Speed ${speed.toFixed(1)}`;}setSpeed(Math.max(2,radius/8));toolbar.append(speedLabel);
 function toggle(parent,label,value,fn){const l=node('label'),input=node('input');input.type='checkbox';input.checked=value;input.onchange=()=>{fn(input.checked);schedule();};l.append(input,document.createTextNode(label));parent.append(l);}
 toggle(toolbar,'Textures',true,v=>textured=v);toggle(toolbar,'Unlit',false,v=>unlit=v);toggle(toolbar,'Vertex colors',true,v=>vertexColors=v);toggle(toolbar,'Fog',true,v=>fogEnabled=v);
 button('Fullscreen',async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await container.requestFullscreen();}catch(e){status.textContent=e.message;}});
 for(const [group,count] of Object.entries(scene.groups))toggle(layers,`${group} (${count})`,enabled.has(group),v=>v?enabled.add(group):enabled.delete(group));
 const search=node('input'),select=node('select');search.placeholder='Find a placed object';search.setAttribute('aria-label','Find a placed object');select.setAttribute('aria-label','Placed object');select.style.maxWidth='360px';
 function searchObjects(){const q=search.value.toLowerCase();select.replaceChildren();draws.forEach((n,i)=>{if((n.name+' '+n.geometry.name).toLowerCase().includes(q))select.add(new Option(n.name,String(i)));});}
 search.oninput=searchObjects;searchObjects();toolbar.append(search,select);button('Focus object',()=>{if(select.value==='')return;const n=draws[Number(select.value)];aim(n.center,Math.max(1,n.radius*1.5));canvas.focus();});
 let loaded=0,failed=0;const urls=[...new Set(scene.materials.map(m=>m.textureUrl).filter(Boolean))];
 const stats=()=>{status.textContent=`${draws.length.toLocaleString()} instances | ${Object.keys(scene.geometry).length} shared mobys | Textures ${loaded}/${urls.length}${failed?` (${failed} failed)`:''} | ${(scene.report.unresolvedForms?.length||0)+scene.warnings.length} unresolved placements`;};stats();
 function fogAt(position){
  let result=null,priority=Infinity;
  for(const volume of scene.fogVolumes||[]){
   const p=transform(volume.inverse,position),inside=volume.shape===0?p.every(v=>Math.abs(v)<=1):volume.shape===1?Math.hypot(...p)<=1:Math.abs(p[1])<=1&&Math.hypot(p[0],p[2])<=1;
   if(!inside||volume.priority>=priority)continue;
   priority=volume.priority;const t=volume.shape===0?(p[0]+1)/2:1,a=volume.sides[0],b=volume.sides[1];
   const start=a.start*t+b.start*(1-t),end=a.end*t+b.end*(1-t);
   result={color:a.color.map((v,i)=>v*t+b.color[i]*(1-t)),curve:[(351-159*(end+start)/(end-start))/2,159*end*start/(end-start)]};
  }
  return result;
 }
 function draw(now){raf=0;if(disposed)return;const dt=Math.min(.05,last?(now-last)/1000:0);last=now;
  const cp=Math.cos(pitch),sp=Math.sin(pitch),sy=Math.sin(yaw),cy=Math.cos(yaw),f=[sy*cp,sp,-cy*cp],right=[cy,0,sy],up=[-sy*sp,cp,cy*sp];
  const movement=[0,0,0],step=speed*dt*(keys.has('ShiftLeft')||keys.has('ShiftRight')?5:1);for(const [code,axis,sign] of [['KeyW',f,1],['KeyS',f,-1],['KeyA',right,-1],['KeyD',right,1],['Space',[0,1,0],1],['ControlLeft',[0,1,0],-1],['ControlRight',[0,1,0],-1]])if(keys.has(code))axis.forEach((v,i)=>movement[i]+=v*sign);const length=Math.hypot(...movement)||1;eye=eye.map((v,i)=>v+movement[i]/length*step);
  const dpr=Math.min(devicePixelRatio||1,2),w=Math.max(1,Math.round(canvas.clientWidth*dpr)),h=Math.max(1,Math.round(canvas.clientHeight*dpr));if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;}gl.viewport(0,0,w,h);gl.clearColor(.06,.09,.14,1);gl.depthMask(true);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);gl.enable(gl.DEPTH_TEST);gl.disable(gl.CULL_FACE);
  const dot=(a,b)=>a.reduce((v,n,i)=>v+n*b[i],0),view=[right[0],up[0],-f[0],0,right[1],up[1],-f[1],0,right[2],up[2],-f[2],0,-dot(right,eye),-dot(up,eye),dot(f,eye),1];
  const near=.03,far=Math.max(20000,radius*10),scale=1/Math.tan(Math.PI*65/360),proj=[scale/(w/h),0,0,0,0,scale,0,0,0,0,(far+near)/(near-far),-1,0,0,2*far*near/(near-far),0];
  gl.uniformMatrix4fv(u.vp,false,multiply(proj,view));gl.uniform1i(u.image,0);gl.uniform1i(u.unlit,unlit);gl.uniform1i(u.vertexColors,vertexColors);
  const fog=fogEnabled?fogAt(eye):null;gl.uniform2fv(u.fogCurve,fog?.curve||[255,0]);gl.uniform3fv(u.fogColor,fog?.color||[0,0,0]);canvas.dataset.fogActive=String(!!fog);
  for(const n of draws)if(n.water){const w=n.water,m=new Float32Array(n.world);m[0]=m[10]=w.tileScale;m[5]=w.amplitude;m[12]=(Math.floor(eye[0]/w.tileSize+.5)+n.waterTile[0])*w.tileSize;m[14]=(Math.floor(eye[2]/w.tileSize+.5)+n.waterTile[1])*w.tileSize;n.renderWorld=m;n.center=[m[12],m[13],m[14]];}
  const visible=draws.filter(n=>enabled.has(n.group)&&(n.group==='Skybox'||dot(n.center.map((v,i)=>v-eye[i]),f)>=-n.radius));
  const opaque=[],transparent=[];
  for(const n of visible)for(const p of n.geometry.parts){if(!p.count)continue;const mat=scene.materials[p.material];(mat.transparent?transparent:opaque).push({n,p,mat,depth:dot(transform(n.renderWorld||n.world,p.center||[0,0,0]).map((v,i)=>v-eye[i]),f)});}
  transparent.sort((a,b)=>b.depth-a.depth);
  const ordered=[...opaque,...transparent];ordered.sort((a,b)=>(a.n.group==='Skybox'?a.n.skyOrder:999)-(b.n.group==='Skybox'?b.n.skyOrder:999));
  for(const {n,p,mat} of ordered){
   const blend=mat.blendEquation;if(mat.transparent){gl.enable(gl.BLEND);gl.blendFunc(gl.SRC_ALPHA,blend==='add'||blend==='subtract'?gl.ONE:gl.ONE_MINUS_SRC_ALPHA);}else{gl.disable(gl.BLEND);}gl.blendEquation(blend==='subtract'?gl.FUNC_REVERSE_SUBTRACT:gl.FUNC_ADD);gl.depthMask(!mat.transparent);gl.uniform1i(u.baked,!p.sceneLighting);gl.depthFunc(gl.LEQUAL);gl.uniform1f(u.alphaCutoff,mat.alphaCutoff??0);
   const sky=n.group==='Skybox',world=sky?new Float32Array(n.world):(n.renderWorld||n.world);if(sky){world[12]+=eye[0];world[14]+=eye[2];gl.depthMask(false);gl.depthFunc(gl.ALWAYS);}
   gl.uniform1i(u.fogEnabled,!!fog&&!sky);gl.uniformMatrix4fv(u.world,false,world);gl.uniform3fv(u.ambient,n.ambient);gl.uniform3fv(u['lightColor[0]'],n.lightColors);gl.uniform3fv(u['lightDirection[0]'],n.lightDirections);gl.uniform4fv(u.tint,mat.diffuseColor||[1,1,1,1]);
   gl.vertexAttribPointer(0,3,gl.FLOAT,false,48,p.vertexOffset);gl.vertexAttribPointer(1,3,gl.FLOAT,false,48,p.vertexOffset+12);gl.vertexAttribPointer(2,2,gl.FLOAT,false,48,p.vertexOffset+24);gl.vertexAttribPointer(3,4,gl.FLOAT,false,48,p.vertexOffset+32);
   const t=textures.get(mat.textureUrl);gl.uniform1i(u.textured,!!(textured&&t));gl.bindTexture(gl.TEXTURE_2D,t||null);if(t){gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,mat.clampU?gl.CLAMP_TO_EDGE:gl.REPEAT);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,mat.clampV?gl.CLAMP_TO_EDGE:gl.REPEAT);}gl.drawElements(gl.TRIANGLES,p.count,gl.UNSIGNED_INT,p.indexOffset);
  }
  canvas.dataset.drawInstances=String(visible.length);canvas.dataset.camera=eye.map(v=>v.toFixed(2)).join(',');canvas.dataset.glError=String(gl.getError());if(keys.size)schedule();else last=0;
 }
 canvas.addEventListener('pointerdown',e=>{if(e.button!==0)return;canvas.focus();canvas.setPointerCapture(e.pointerId);drag=[e.clientX,e.clientY];},{signal});
 canvas.addEventListener('pointermove',e=>{if(!drag)return;yaw+=(e.clientX-drag[0])*.004;pitch=Math.max(-1.55,Math.min(1.55,pitch-(e.clientY-drag[1])*.004));drag=[e.clientX,e.clientY];schedule();},{signal});
 canvas.addEventListener('pointerup',()=>drag=null,{signal});canvas.addEventListener('lostpointercapture',()=>drag=null,{signal});
 canvas.addEventListener('wheel',e=>{e.preventDefault();setSpeed(speed*Math.exp(-e.deltaY*.001));},{passive:false,signal});
 canvas.addEventListener('keydown',e=>{if(['KeyW','KeyA','KeyS','KeyD','Space','ControlLeft','ControlRight','ShiftLeft','ShiftRight'].includes(e.code)){e.preventDefault();keys.add(e.code);schedule();}},{signal});
 canvas.addEventListener('keyup',e=>keys.delete(e.code),{signal});canvas.addEventListener('blur',()=>{keys.clear();drag=null;},{signal});
 const observer=new ResizeObserver(schedule);observer.observe(canvas);
 signal.addEventListener('abort',()=>{disposed=true;keys.clear();cancelAnimationFrame(raf);observer.disconnect();for(const t of textures.values())gl.deleteTexture(t);gl.deleteBuffer(vb);gl.deleteBuffer(ib);gl.deleteProgram(program);shaders.forEach(s=>gl.deleteShader(s));gl.getExtension('WEBGL_lose_context')?.loseContext();},{once:true});
 aim(center,radius);canvas.focus();
 let next=0;await Promise.all(Array.from({length:Math.min(6,urls.length)},async()=>{while(next<urls.length&&!signal.aborted){const url=urls[next++];try{let r;for(let attempt=0;attempt<3;attempt++){try{r=await fetch(url,{signal});if(!r.ok)throw Error(r.status);break;}catch(e){if(signal.aborted||attempt===2)throw e;}}const bitmap=await createImageBitmap(await r.blob(),{premultiplyAlpha:'none',colorSpaceConversion:'none'});if(disposed){bitmap.close();return;}const t=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,t);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,bitmap);bitmap.close();gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR_MIPMAP_LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.REPEAT);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.REPEAT);gl.generateMipmap(gl.TEXTURE_2D);textures.set(url,t);loaded++;schedule();}catch(e){if(signal.aborted)return;failed++;}stats();}}));
};
