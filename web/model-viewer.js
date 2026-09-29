// Offline WebGL preview; all assets come from the local extraction server.
window.createModelViewer = async function(container, url, signal, initialBank, options={}) {
  const node=(tag,text)=>{const n=document.createElement(tag);if(text)n.textContent=text;return n;};
  const status=node('p','Decoding moby...'); container.append(status);
  const response=await fetch(url,{signal});if(!response.ok)throw Error(await response.text());
  const model=await response.json();if(signal.aborted)return;
  const toolbar=node('div');toolbar.className='model-controls';
  const canvas=node('canvas');canvas.className='model-canvas';canvas.tabIndex=0;canvas.setAttribute('aria-label','3D moby. Drag to orbit, Shift-drag to pan, scroll to zoom.');
  const help=node('small','Drag to orbit | Shift-drag to pan | Scroll to zoom');
  container.replaceChildren(toolbar,canvas,help,status);
  const gl=canvas.getContext('webgl',{antialias:true,alpha:false});if(!gl)throw Error('WebGL is unavailable in this browser.');
  const shader=(type,source)=>{const s=gl.createShader(type);gl.shaderSource(s,source);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(s));return s;};
  const vs=shader(gl.VERTEX_SHADER,`attribute vec3 position;attribute vec3 normal;attribute vec2 uv;attribute vec3 color;uniform mat4 mvp;varying vec3 n;varying vec2 tex;varying vec3 col;void main(){gl_Position=mvp*vec4(position,1.0);n=normal;tex=uv;col=color;}`);
  const fs=shader(gl.FRAGMENT_SHADER,`precision mediump float;varying vec3 n;varying vec2 tex;varying vec3 col;uniform sampler2D image;uniform bool textured;uniform bool wire;void main(){vec4 c=textured?texture2D(image,tex):vec4(0.65,0.77,0.8,1.0);if(c.a<0.15)discard;float light=0.35+0.65*abs(dot(normalize(n),normalize(vec3(0.4,-0.6,1.0))));gl_FragColor=wire?vec4(0.36,0.9,0.84,1.0):vec4(c.rgb*col*light,1.0);}`);
  const program=gl.createProgram();gl.attachShader(program,vs);gl.attachShader(program,fs);gl.linkProgram(program);if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(program));gl.useProgram(program);
  const attr={};for(const k of ['position','normal','uv','color'])attr[k]=gl.getAttribLocation(program,k);
  const uniform={};for(const k of ['mvp','textured','wire','image'])uniform[k]=gl.getUniformLocation(program,k);
  let disposed=false,raf=0,lod=model.defaultLod||0,wire=false,textured=true,az=model.skeleton?Math.PI+0.65:0.65,el=0.3,zoom=1,pan=[0,0],drag=null;
  const min=model.bounds[0],max=model.bounds[1],center=min.map((v,i)=>(v+max[i])/2),radius=Math.max(0.0001,Math.hypot(...max.map((v,i)=>(v-min[i])/2)));
  const chunks=[];const textures=[];
  let bank=null,clip=null,playing=false,time=0,lastTime=0,poseDirty=false,loadSequence=0;
  const multiply=(a,b)=>{const out=new Float32Array(16);for(let c=0;c<4;c++)for(let r=0;r<4;r++)for(let k=0;k<4;k++)out[c*4+r]+=a[k*4+r]*b[c*4+k];return out;};
  const slerp=(a,b,t)=>{let dot=a.reduce((v,x,i)=>v+x*b[i],0),bb=b;if(dot<0){dot=-dot;bb=b.map(v=>-v);}dot=Math.min(1,dot);let x=1-t,y=t;if(dot<0.9995){const theta=Math.acos(dot),sin=Math.sin(theta);x=Math.sin((1-t)*theta)/sin;y=Math.sin(t*theta)/sin;}const q=a.map((v,i)=>v*x+bb[i]*y),n=Math.hypot(...q)||1;return q.map(v=>v/n);};
  function skinMatrices(){
    const bones=model.skeleton.map(b=>({...b}));
    if(clip)for(const track of clip.tracks){const keys=track.frames;if(!keys.length||!bones[track.bone])continue;let a=keys[0],b=a;for(let i=0;i<keys.length;i++){a=keys[i];b=keys[Math.min(i+1,keys.length-1)];if(time<=b.time)break;}const t=b.time===a.time?0:Math.max(0,Math.min(1,(time-a.time)/(b.time-a.time)));for(const k of ['rotation','scale','translation'])if(a[k])bones[track.bone][k]=k==='rotation'?slerp(a[k],b[k],t):a[k].map((v,i)=>(v+(b[k][i]-v)*t)*(k==='translation'?model.skeletonScale:1));}
    const world=[],skin=[];
    for(const b of bones){const [x,y,z,w]=b.rotation,[sx,sy,sz]=b.scale,[tx,ty,tz]=b.translation;let m=[(1-2*y*y-2*z*z)*sx,(2*x*y+2*w*z)*sx,(2*x*z-2*w*y)*sx,0,(2*x*y-2*w*z)*sy,(1-2*x*x-2*z*z)*sy,(2*y*z+2*w*x)*sy,0,(2*x*z+2*w*y)*sz,(2*y*z-2*w*x)*sz,(1-2*x*x-2*y*y)*sz,0,tx,ty,tz,1];if(b.parent>=0)m=multiply(world[b.parent],m);world.push(m);skin.push(multiply(m,b.inverseBind));}return skin;
  }

  function uploadGeometry(matrices=null){
    const bucket=new Map();
    for(const m of model.meshes){if(matrices&&m.lod!==0)continue;const key=m.lod+':'+m.material;if(!bucket.has(key))bucket.set(key,{lod:m.lod,material:m.material,values:[],lines:[]});const b=bucket.get(key);
      const positions=matrices&&m.weights?m.positions.map((p,i)=>{const out=[0,0,0];for(let j=0;j<m.joints.length;j++){const weight=m.weights[i][j];if(!weight)continue;const mat=matrices[m.joints[j]];for(let k=0;k<3;k++)out[k]+=weight*(mat[k]*p[0]+mat[4+k]*p[1]+mat[8+k]*p[2]+mat[12+k]);}return out;}):m.positions;
      for(let i=0;i<m.indices.length;i+=3){const ids=m.indices.slice(i,i+3),p=ids.map(j=>positions[j]);const a=p[1].map((v,k)=>v-p[0][k]),c=p[2].map((v,k)=>v-p[0][k]);let n=[a[1]*c[2]-a[2]*c[1],a[2]*c[0]-a[0]*c[2],a[0]*c[1]-a[1]*c[0]],len=Math.hypot(...n)||1;n=n.map(v=>v/len);const verts=ids.map((j,k)=>[...p[k].map((v,d)=>(v-center[d])/radius),...n,...(m.uvs[j]||[0,0]),...(m.colors[j]||[1,1,1])]);b.values.push(...verts.flat());b.lines.push(...verts[0],...verts[1],...verts[1],...verts[2],...verts[2],...verts[0]);}}
    const old=new Map(chunks.map(c=>[c.lod+':'+c.material,c]));chunks.length=0;
    for(const [key,b] of bucket){const prev=old.get(key);old.delete(key);const upload=(values,handle)=>{handle=handle||gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,handle);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(values),model.skeleton?gl.DYNAMIC_DRAW:gl.STATIC_DRAW);return handle;};chunks.push({lod:b.lod,material:b.material,solid:upload(b.values,prev?.solid),lines:upload(b.lines,prev?.lines),count:b.values.length/11,lineCount:b.lines.length/11});}
    for(const b of old.values()){gl.deleteBuffer(b.solid);gl.deleteBuffer(b.lines);}
  }
  uploadGeometry();
  function schedule(){if(!disposed&&!raf)raf=requestAnimationFrame(draw);}
  function draw(now){raf=0;if(disposed)return;
    if(playing&&clip){if(lastTime)time=(time+Math.min(0.1,(now-lastTime)/1000)*Number(speed.value))%Math.max(clip.duration,0.001);lastTime=now;poseDirty=true;}
    if(poseDirty){uploadGeometry(clip?skinMatrices():null);poseDirty=false;seek.value=time;clock.textContent=time.toFixed(2)+' / '+(clip?.duration||0).toFixed(2)+' s';}
const dpr=Math.min(devicePixelRatio||1,2),w=Math.max(1,Math.round(canvas.clientWidth*dpr)),h=Math.max(1,Math.round(canvas.clientHeight*dpr));if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;}gl.viewport(0,0,w,h);gl.clearColor(0.07,0.1,0.14,1);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);gl.enable(gl.DEPTH_TEST);gl.disable(gl.CULL_FACE);
    const sa=Math.sin(az),ca=Math.cos(az),se=Math.sin(el),ce=Math.cos(el),dist=3.3*zoom;
    const view=[ca,-sa*se,sa*ce,0,-sa,-ca*se,ca*ce,0,0,ce,se,0,pan[0],pan[1],-dist,1];
    // Skinned GDE bind geometry is Y-up; world geometry uses Z-up.
    if(model.skeleton){const y=view.slice(4,8);view.splice(4,4,...view.slice(8,12));view.splice(8,4,...y.map(v=>-v));}
    const near=0.002,far=200,f=1/Math.tan(Math.PI/8),proj=[f/(w/h),0,0,0,0,f,0,0,0,0,(far+near)/(near-far),-1,0,0,2*far*near/(near-far),0],mvp=new Float32Array(16);
    for(let c=0;c<4;c++)for(let r=0;r<4;r++)for(let k=0;k<4;k++)mvp[c*4+r]+=proj[k*4+r]*view[c*4+k];
    gl.uniformMatrix4fv(uniform.mvp,false,mvp);gl.uniform1i(uniform.wire,wire);gl.uniform1i(uniform.image,0);
    for(const b of chunks){if(b.lod!==lod)continue;gl.bindBuffer(gl.ARRAY_BUFFER,wire?b.lines:b.solid);for(const [name,num,off] of [['position',3,0],['normal',3,12],['uv',2,24],['color',3,32]]){gl.enableVertexAttribArray(attr[name]);gl.vertexAttribPointer(attr[name],num,gl.FLOAT,false,44,off);}const t=textures[b.material];gl.uniform1i(uniform.textured,!!(textured&&t));gl.bindTexture(gl.TEXTURE_2D,t||null);gl.drawArrays(wire?gl.LINES:gl.TRIANGLES,0,wire?b.lineCount:b.count);}
    if(playing&&clip)schedule();
  }
  function toggle(label,value,change){const l=node('label'),input=node('input');input.type='checkbox';input.checked=value;input.onchange=()=>{change(input.checked);schedule();};l.append(input,document.createTextNode(label));toolbar.append(l);}
  toggle('Textures',true,v=>textured=v);toggle('Wireframe',false,v=>wire=v);
  const lodSelect=node('select');lodSelect.setAttribute('aria-label','Moby detail level');for(const l of model.lods)lodSelect.add(new Option('LOD '+l.level,l.level));lodSelect.onchange=()=>{lod=Number(lodSelect.value);schedule();};lodSelect.value=String(lod);toolbar.append(lodSelect);
  const reset=node('button','Reset view');reset.onclick=()=>{az=model.skeleton?Math.PI+0.65:0.65;el=0.3;zoom=1;pan=[0,0];schedule();};toolbar.append(reset);
  const bankSelect=node('select'),clipSelect=node('select'),play=node('button','Play'),seek=node('input'),clock=node('span'),speed=node('select');
  if(model.skeleton&&!options.thumbnail){
    const controls=node('div');controls.className='model-controls animation-controls';container.insertBefore(controls,canvas);
    bankSelect.setAttribute('aria-label','Animation bank');clipSelect.setAttribute('aria-label','Animation clip');seek.setAttribute('aria-label','Animation timeline');seek.type='range';seek.min=0;seek.max=1;seek.step=0.001;seek.value=0;seek.style.minWidth='120px';speed.setAttribute('aria-label','Playback speed');for(const n of [0.25,0.5,1,2])speed.add(new Option(n+'x',n,n===1,n===1));
    controls.append(bankSelect,clipSelect,play,seek,clock,speed);clipSelect.add(new Option('Bind pose',''));play.disabled=true;seek.disabled=true;
    const banks=model.animations||[];
    if(!banks.length){controls.replaceChildren(node('small','Skeleton decoded; no matching animation bank was found.'));}
    for(const a of banks)bankSelect.add(new Option(a.name,a.id));
    async function loadBank(id){const seq=++loadSequence;playing=false;lastTime=0;play.textContent='Play';play.disabled=true;clip=null;poseDirty=true;schedule();clipSelect.replaceChildren(new Option('Loading clips?',''));try{const r=await fetch('/asset/'+id+'/animation',{signal});if(!r.ok)throw Error(await r.text());const data=await r.json();if(disposed||seq!==loadSequence)return;if(data.maxBone>=model.skeleton.length)throw Error('Animation bone indices do not match this skeleton');bank=data;clipSelect.replaceChildren(new Option('Bind pose',''));bank.clips.forEach((c,i)=>clipSelect.add(new Option(c.name+' ('+c.duration.toFixed(2)+'s)',i)));clipSelect.value=bank.clips.length?'0':'';chooseClip();}catch(e){if(!disposed&&seq===loadSequence){clipSelect.replaceChildren(new Option('Unavailable',''));status.textContent=e.message;}}}
    function chooseClip(){clip=clipSelect.value===''?null:bank.clips[Number(clipSelect.value)];time=0;lastTime=0;playing=!!clip&&!window.assetPlaybackPaused;play.textContent=playing?'Pause':'Play';play.disabled=!clip;seek.disabled=!clip;seek.max=clip?.duration||1;lod=clip?0:(model.defaultLod||0);lodSelect.value=String(lod);lodSelect.disabled=!!clip;poseDirty=true;schedule();}
    bankSelect.onchange=()=>loadBank(bankSelect.value);clipSelect.onchange=chooseClip;
    play.onclick=()=>{playing=!playing;window.assetPlaybackPaused=!playing;try{sessionStorage.setItem('assetPlaybackPaused',String(!playing));}catch{}lastTime=0;play.textContent=playing?'Pause':'Play';schedule();};seek.oninput=()=>{time=Number(seek.value);lastTime=0;poseDirty=true;schedule();};
    if(banks.length){if(initialBank&&banks.some(b=>b.id===initialBank))bankSelect.value=initialBank;loadBank(bankSelect.value);}
  }
  canvas.onpointerdown=e=>{drag=[e.clientX,e.clientY];canvas.setPointerCapture(e.pointerId);};canvas.onpointerup=()=>drag=null;canvas.onpointercancel=()=>drag=null;
  canvas.onpointermove=e=>{if(!drag)return;const dx=e.clientX-drag[0],dy=e.clientY-drag[1];drag=[e.clientX,e.clientY];if(e.shiftKey||e.buttons===2){pan[0]+=dx*zoom*0.004;pan[1]-=dy*zoom*0.004;}else{az-=dx*0.01;el=Math.max(-1.5,Math.min(1.5,el+dy*0.01));}schedule();};canvas.oncontextmenu=e=>e.preventDefault();
  canvas.addEventListener('wheel',e=>{e.preventDefault();zoom=Math.max(0.03,Math.min(30,zoom*Math.exp(e.deltaY*0.001)));schedule();},{passive:false});
  const resize=new ResizeObserver(schedule);resize.observe(canvas);
  signal.addEventListener('abort',()=>{disposed=true;cancelAnimationFrame(raf);resize.disconnect();for(const c of chunks){gl.deleteBuffer(c.solid);gl.deleteBuffer(c.lines);}for(const t of textures)if(t)gl.deleteTexture(t);gl.deleteProgram(program);gl.deleteShader(vs);gl.deleteShader(fs);gl.getExtension('WEBGL_lose_context')?.loseContext();},{once:true});
  const textureReady=[];
  let loaded=0,failed=0;const updateStatus=()=>status.textContent=`${model.vertexCount.toLocaleString()} vertices | ${model.triangleCount.toLocaleString()} triangles across ${model.lods.length} LOD(s) | ${loaded}/${model.materials.length} textured materials${failed?' | '+failed+' texture failures':''}`;
  model.materials.forEach((m,i)=>{if(!m.textureUrl)return;const img=new Image();let resolve;textureReady.push(new Promise(r=>resolve=r));img.onload=()=>{resolve();if(disposed)return;const t=gl.createTexture();textures[i]=t;gl.bindTexture(gl.TEXTURE_2D,t);gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,false);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,img);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);const pot=n=>(n&(n-1))===0;const wrap=pot(img.width)&&pot(img.height)?gl.REPEAT:gl.CLAMP_TO_EDGE;gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,wrap);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,wrap);loaded++;updateStatus();schedule();};img.onerror=()=>{resolve();if(!disposed){failed++;updateStatus();}};img.src=m.textureUrl;});
  if(model.warnings?.length){const note=node('small',model.warnings.join(' '));note.className='muted';container.append(note);}
  updateStatus();schedule();
  if(options.thumbnail){await Promise.all(textureReady);if(signal.aborted)throw new DOMException('Aborted','AbortError');draw(0);return await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));}
  return model;
};
