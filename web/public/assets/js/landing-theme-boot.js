try{
  const savedTheme=localStorage.getItem('omnexa-theme');
  if(savedTheme==='light'||savedTheme==='dark') document.documentElement.dataset.theme=savedTheme;
}catch(e){}
