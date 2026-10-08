(function(){
  if(!window.THREE) return;
  var reduce=!!(window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  // our GLBs: accessor 0 = POSITION (float32 vec3), accessor 1 = indices (uint32), one primitive
  function b64(s){ var bin=atob(s), n=bin.length, u=new Uint8Array(n); for(var i=0;i<n;i++) u[i]=bin.charCodeAt(i); return u.buffer; }
  function getJSON(url){ return fetch(url).then(function(r){ if(!r.ok) throw new Error('HTTP '+r.status); return r.json(); }); }
  function getModel(url){ return getJSON(url).then(function(j){
    if(!j.parts) return b64(j.glb);
    var base=url.replace(/[^\/]*$/,'');   // large models ship as several base64 parts (each under the host's per-file limit)
    return Promise.all(j.parts.map(function(p){ return getJSON(base+p); })).then(function(a){ return b64(a.map(function(x){ return x.glb; }).join('')); });
  }); }
  function parseGLB(buf){
    var dv=new DataView(buf), jl=dv.getUint32(12,true);
    var js=JSON.parse(new TextDecoder().decode(new Uint8Array(buf,20,jl)));
    var bin=20+jl+8, bv=js.bufferViews;
    function view(i,T){ var o=bin+(bv[i].byteOffset||0); return new T(buf.slice(o,o+bv[i].byteLength)); }
    var g=new THREE.BufferGeometry();
    g.setAttribute('position',new THREE.BufferAttribute(view(js.accessors[0].bufferView,Float32Array),3));
    g.setIndex(new THREE.BufferAttribute(view(js.accessors[1].bufferView,Uint32Array),1));
    g.computeVertexNormals(); return g;
  }
  function scene(host,W,H){
    var sc=new THREE.Scene(), cam=new THREE.PerspectiveCamera(42,W/H,0.01,100);
    var rn=new THREE.WebGLRenderer({antialias:true,alpha:true,preserveDrawingBuffer:true});
    rn.setSize(W,H); rn.setPixelRatio(Math.min(window.devicePixelRatio||1,2)); host.appendChild(rn.domElement);
    sc.add(new THREE.HemisphereLight(0xdae7ff,0x1b2534,1.35));
    var d=new THREE.DirectionalLight(0xffffff,1.15); d.position.set(3,5,2); sc.add(d);
    var d2=new THREE.DirectionalLight(0x8fb6f0,0.5); d2.position.set(-4,2,-3); sc.add(d2);
    var grp=new THREE.Group(); sc.add(grp);
    return {sc:sc,cam:cam,rn:rn,grp:grp};
  }
  function place(v,g,mat){
    var grp=v.grp, cam=v.cam;
    grp.add(new THREE.Mesh(g,mat)); grp.updateMatrixWorld(true);   // the GLBs are already Y-up, metres, centred
    var bb=new THREE.Box3().setFromObject(grp), sz=bb.getSize(new THREE.Vector3()), ctr=bb.getCenter(new THREE.Vector3());
    var k=1.6/(Math.max(sz.x,sz.y,sz.z)||1); grp.scale.setScalar(k); grp.position.set(-ctr.x*k,-ctr.y*k,-ctr.z*k);
    var dir=new THREE.Vector3(1.35,0.95,1.35).normalize(), rt=new THREE.Vector3().crossVectors(dir,new THREE.Vector3(0,1,0)).normalize();
    var up=new THREE.Vector3().crossVectors(rt,dir).normalize(), tv=Math.tan(cam.fov*Math.PI/360), th=tv*cam.aspect, t=0, c=new THREE.Vector3();
    var hx=sz.x*k/2, hy=sz.y*k/2, hz=sz.z*k/2;
    for(var i=0;i<8;i++){ c.set(i&1?hx:-hx,i&2?hy:-hy,i&4?hz:-hz); var dp=c.dot(dir);
      t=Math.max(t,dp+Math.abs(c.dot(rt))/th,dp+Math.abs(c.dot(up))/tv); }
    t=(t||1)*1.04; cam.position.copy(dir).multiplyScalar(t); cam.lookAt(0,0,0);
    cam.near=Math.max(t*0.004,0.001); cam.far=t*8; cam.updateProjectionMatrix();
  }
  function controls(el,v,getSpin){
    var drag=false,px=0,py=0;
    el.addEventListener('pointerdown',function(e){ if(e.target.tagName==='BUTTON') return; drag=true; px=e.clientX; py=e.clientY; try{el.setPointerCapture(e.pointerId);}catch(_){}});
    el.addEventListener('pointerup',function(){drag=false;}); el.addEventListener('pointercancel',function(){drag=false;});
    el.addEventListener('pointermove',function(e){ if(!drag) return; v.grp.rotation.y+=(e.clientX-px)*0.01; v.grp.rotation.x+=(e.clientY-py)*0.01; px=e.clientX; py=e.clientY; });
    el.addEventListener('wheel',function(e){ e.preventDefault(); v.cam.position.multiplyScalar(e.deltaY>0?1.08:0.93); },{passive:false});
    el.style.touchAction='none';
  }
  function mat(){ return new THREE.MeshStandardMaterial({color:0x9fb8dd,metalness:0.15,roughness:0.55,flatShading:true,side:THREE.DoubleSide}); }
  // hero
  var host=document.getElementById('viewer');
  if(host){
    var v=scene(host,host.clientWidth,host.clientHeight), spin=!reduce, btn=document.getElementById('spin');
    btn.textContent=spin?'pause rotation':'resume rotation';
    btn.onclick=function(){ spin=!spin; this.textContent=spin?'pause rotation':'resume rotation'; };
    controls(host,v);
    getModel(host.dataset.glb)
      .then(function(b){ place(v,parseGLB(b),mat()); host.dataset.state='loaded'; })
      .catch(function(e){ host.dataset.state='failed'; host.insertAdjacentHTML('beforeend','<div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#64748b;font-size:13px">Model could not be loaded ('+(e&&e.message||e)+')</div>'); });
    (function loop(){ requestAnimationFrame(loop); if(spin) v.grp.rotation.y+=0.0042; v.rn.render(v.sc,v.cam); })();
    window.addEventListener('resize',function(){ var w=host.clientWidth,h=host.clientHeight; v.cam.aspect=w/h; v.cam.updateProjectionMatrix(); v.rn.setSize(w,h); });
  }
  // tiles: one live viewer at a time
  var cur=null;
  function wire(fig){ var b=fig.querySelector('.sgo'); b.disabled=false; b.textContent='interact'; b.onclick=function(){ load(fig); }; }
  function dispose(x){ if(!x||x.dead) return; x.dead=true; try{ x.geo.dispose(); x.mat.dispose(); x.rn.forceContextLoss(); x.rn.dispose(); }catch(e){}
    [x.rn.domElement,x.hint,x.close].forEach(function(n){ if(n&&n.parentNode) n.parentNode.removeChild(n); });
    x.fig.classList.remove('live'); if(cur===x) cur=null; wire(x.fig); }
  function load(fig){
    var b=fig.querySelector('.sgo'); b.disabled=true; b.textContent='loading';
    getModel(fig.dataset.glb)
      .then(function(buf){ build(fig,buf); })
      .catch(function(){ b.disabled=false; b.textContent='retry'; b.onclick=function(){ load(fig); }; });
  }
  function build(fig,buf){
    if(cur) dispose(cur);
    var sh=fig.querySelector('.sshell'), b=fig.querySelector('.sgo'), W=sh.clientWidth||300, H=sh.clientHeight||225;
    var v=scene(sh,W,H), g=parseGLB(buf), m=mat(); place(v,g,m);
    sh.insertBefore(v.rn.domElement,b);
    var hint=document.createElement('div'); hint.className='shint'; hint.textContent='drag · scroll'; sh.appendChild(hint);
    var close=document.createElement('button'); close.className='sx'; close.type='button'; close.setAttribute('aria-label','Close the model and show the still image'); close.innerHTML='&times;'; sh.appendChild(close);
    var x={fig:fig,rn:v.rn,geo:g,mat:m,hint:hint,close:close,dead:false,cam:v.cam}, spin=!reduce;
    b.disabled=false; b.textContent=spin?'pause':'spin'; b.onclick=function(){ spin=!spin; b.textContent=spin?'pause':'spin'; };
    close.onclick=function(){ dispose(x); };
    controls(sh,v); fig.classList.add('live'); cur=x;
    (function loop(){ if(x.dead) return; requestAnimationFrame(loop); if(spin) v.grp.rotation.y+=0.0042; v.rn.render(v.sc,v.cam); })();
  }
  window.addEventListener('resize',function(){ if(!cur||cur.dead) return; var sh=cur.fig.querySelector('.sshell'); cur.cam.aspect=sh.clientWidth/sh.clientHeight; cur.cam.updateProjectionMatrix(); cur.rn.setSize(sh.clientWidth,sh.clientHeight); });
  [].slice.call(document.querySelectorAll('figure.smp')).forEach(wire);
})();
