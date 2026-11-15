document.getElementById('yr').textContent = new Date().getFullYear();

/* Returning signed-in visitors should land in the app, not on registration.
   This only reads an existing session marker. The public page performs no
   authentication and issues no authenticated network calls of any kind -
   a raw-source test asserts those helper names never appear here. */
(function(){
  let signedIn=false;
  try{ signedIn = sessionStorage.getItem('isLoggedIn')==='true' || !!sessionStorage.getItem('token'); }
  catch(e){ signedIn=false; }
  if(!signedIn) return;
  ['hero-primary-cta','bottom-cta-btn'].forEach(function(id){
    const el=document.getElementById(id);
    if(el){ el.setAttribute('href','bots.html'); el.textContent='Go to your bots'; }
  });
  document.querySelectorAll('[data-plan-cta]').forEach(function(el){
    if(el.getAttribute('data-plan-cta')==='business') return;   /* sales contact stays */
    el.setAttribute('href','pricing.html');
    el.textContent='View plans';
  });
})();


/* The product demo plays only while it is on screen, and never under reduced motion. */
(function(){
  const v=document.querySelector('.demo-video');
  if(!v || !('IntersectionObserver' in window)) return;
  if(matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  new IntersectionObserver(function(entries){
    entries.forEach(function(e){
      if(!e.isIntersecting){ v.pause(); return; }
      v.preload='auto';
      const p=v.play(); if(p) p.catch(function(){});
    });
  },{rootMargin:'200px 0px'}).observe(v);
})();

window.addEventListener('load', function(){
  if(typeof gsap==='undefined') return;           /* CDN blocked: page still works, just static */
  gsap.registerPlugin(ScrollTrigger);
  const mm=gsap.matchMedia();

  mm.add({motionOK:"(prefers-reduced-motion: no-preference)",
          reduce:"(prefers-reduced-motion: reduce)"}, function(ctx){
    const reduce=ctx.conditions.reduce;

    /* ---- cinema: the film pins under the header and steps through the chapters ---- */
    const cinema=document.getElementById('cinema');
    if(cinema){
      const hdr=document.querySelector('header').offsetHeight;
      document.documentElement.style.setProperty('--hdr',hdr+'px');
      cinema.classList.toggle('is-pinned',!reduce);
      const films=[document.getElementById('robot')]
        .concat(gsap.utils.toArray('#cinema .chapter video'));
      if(reduce){ films.forEach(function(v){ v.pause(); }); }
      else{
        /* hero entrance - staggered cascade, runs once on load */
        gsap.from(".hero > div:first-child > *",
          {opacity:0,y:24,duration:.8,ease:"power3.out",stagger:.09,delay:.1});
        const chapters=gsap.utils.toArray('#cinema .chapter');
        const play=function(v){ const p=v.play(); if(p) p.catch(function(){}); };
        let step=-1;
        /* step 0 is the hero film, steps 1-3 the chapters; only the visible clip plays */
        const show=function(next){
          if(next===step) return;
          step=next;
          cinema.dataset.step=next;
          chapters.forEach(function(c,i){ c.classList.toggle('is-active',i+1===next); });
          films.forEach(function(v,i){ if(i===next) play(v); else v.pause(); });
        };
        show(0);
        /* the hero and each chapter own an equal slice of the pin, so the last
           chapter still has room to play before the page scrolls on */
        const slices=chapters.length+1;
        ScrollTrigger.create({trigger:cinema, start:"top top+="+hdr,
          end:function(){ return "+="+Math.round(innerHeight*slices*.8); },
          pin:true, anticipatePin:1, invalidateOnRefresh:true,
          snap:{snapTo:[0].concat(chapters.map(function(c,i){ return (i+1.5)/slices; }),[1]),
                duration:{min:.2,max:.6}, ease:"power1.inOut"},
          onUpdate:function(self){ show(Math.min(chapters.length,Math.floor(self.progress*slices))); }});
        /* pause the visible clip once the whole cinema has scrolled away */
        new IntersectionObserver(function(entries){
          const v=films[step];
          if(v){ if(entries[entries.length-1].isIntersecting) play(v); else v.pause(); }
        }).observe(cinema);
        /* fetch the chapter clips once the page is idle, so the first swap is instant */
        const warm=function(){ films.forEach(function(v){ v.preload='auto'; }); };
        if('requestIdleCallback' in window) requestIdleCallback(warm); else setTimeout(warm,1200);
      }
    }

    /* ---- scroll reveal ----
       Elements are hidden here with gsap.set(), NOT in CSS, so if the GSAP CDN
       is blocked the page simply renders fully visible instead of blank.
       ScrollTrigger.batch groups entries into one tween per batch rather than
       one trigger per element, and no scroll listener is involved. */
    if(!reduce){
      const reveal = gsap.utils.toArray([
        "section:not(.hero) > .eyebrow",
        "section:not(.hero) > h2",
        "section:not(.hero) > .lede",
        ".step", ".zig > div", ".uc", ".chan .c", ".roadmap",
        ".facts", ".founder", ".trust", ".notice", ".plan",
        "#faq details", ".closing .inner > *"
      ].join(","));

      gsap.set(reveal,{opacity:0,y:26});
      ScrollTrigger.batch(reveal,{
        start:"top 88%",
        once:true,                         /* reveal once; no re-hide scrolling back */
        onEnter:(batch)=>gsap.to(batch,{
          opacity:1, y:0, duration:.7, ease:"power3.out",
          stagger:.08, overwrite:true
        })
      });
    }

  });
});
