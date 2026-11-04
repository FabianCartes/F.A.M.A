async (page) => {
 const profile={architecture:'audio_cnn',channels:1,preprocessing:'mono_mel',windowing:'energy_peak_pad',window_hop_seconds:0.5,audio:{target_sr:8000,duration_seconds:1,n_mels:32,n_fft:256,hop_length:64,f_min:0,f_max:4000,use_gpu_frontend:false}};
 const calls=[]; let loggedIn=true;
 await page.route('**/api/**',async route=>{
  const req=route.request(),url=req.url();calls.push({url,method:req.method(),body:req.postData()});
  if(url.includes('/auth/web/logout')){loggedIn=false;await route.fulfill({status:204});return;}
  if(url.includes('/auth/web/me')&&!loggedIn){await route.fulfill({status:401,contentType:'application/json',body:JSON.stringify({detail:'Synthetic anonymous'})});return;}
  let data={};
  if(url.includes('/auth/web/me'))data={id:1,email:'owner@example.test',nombre_completo:'Synthetic Owner',rol:'investigador',activo:true};
  else if(url.includes('include_imported=true'))data={datasets:[{source_type:'imported',id:'synthetic-wav',name:'Synthetic WAV',eligible:true,reasons:[],preparations:[{snapshot_id:'snapshot',prepared_version:'version',eligible:true,reasons:[],profile,warnings:['low_group_count']}]}]};
  else if(url.endsWith('/members'))data={snapshot_id:'snapshot',members:[{member_id:'member',class_name:'ants',original_path:'ants/a.wav',size_bytes:44,sha256:'synthetic'}]};
  else if(url.endsWith('/snapshots'))data={id:'snapshot',dataset_id:'synthetic-wav',name:'Synthetic WAV',state:'ready',file_count:1};
  else if(url.endsWith('/preparations'))data={snapshot_id:'snapshot',version_id:'new-version',state:'ready',profile,class_to_index:{ants:0},warnings:['low_group_count'],seed:42};
  else if(url.includes('/datasets'))data={datasets:[]};
  else if(url.includes('/history'))data={history:[]};
  else if(url.includes('/progress'))data={status:'checkpoint_persisted',logs:[]};
  await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
 });
 await page.goto('http://127.0.0.1:3417/');
 await page.getByText('Synthetic Owner',{exact:true}).waitFor();
 const menu = page.getByRole('button',{name:'Abrir menú',exact:true});
 if(await menu.isVisible()) await menu.click();
 await page.getByRole('button',{name:'Entrenamiento',exact:true}).click();
 await page.getByLabel('Tipo de fuente').selectOption('imported');
 await page.getByLabel('Colección importada').selectOption('synthetic-wav');
 await page.getByLabel('Preparación existente').selectOption('0');
 if(!await page.getByTestId('architecture-select').isDisabled())throw Error('Architecture not locked');
 if(!await page.getByRole('button',{name:'2 Modelos (Dúo)',exact:true}).isDisabled())throw Error('Topology not locked');
 await page.getByLabel('Épocas de Entrenamiento',{exact:true}).fill('1');
 await page.getByLabel(/Batch Size/).fill('2');
 await page.getByRole('button',{name:'Iniciar Entrenamiento Local (1 Modelo)',exact:true}).click();
 await page.getByText(/Checkpoint persistido; evaluación pendiente/).waitFor();
 let starts=calls.filter(c=>c.url.endsWith('/start'));
 if(starts.length!==1)throw Error('Start count '+starts.length);
 const first=JSON.parse(starts[0].body);
 if(first.imported_dataset_id!=='synthetic-wav'||first.snapshot_id!=='snapshot'||first.imported_prepared_version!=='version'||first.architecture!=='AudioCNN'||first.epochs!==1||first.batch_size!==2||first.dataset_name!==undefined||JSON.stringify(first.audio_config)!==JSON.stringify(profile.audio))throw Error('Wrong existing payload');
 await page.getByRole('button',{name:'Crear snapshot y obtener plantilla',exact:true}).click();
 await page.getByLabel('Mapa explícito JSON').waitFor();
 await page.waitForFunction(()=>document.querySelector('textarea')&&Array.from(document.querySelectorAll('textarea')).some(x=>x.value.includes('member_id')));
 const template=JSON.parse(await page.getByLabel('Mapa explícito JSON').inputValue());
 if(template[0].recording_id!==''||template[0].group_id!=='')throw Error('Groups inferred');
 await page.getByLabel('Mapa explícito JSON').fill(JSON.stringify([{member_id:'member',recording_id:'explicit-recording',group_id:'explicit-group'}]));
 await page.getByLabel('Procedencia JSON').fill(JSON.stringify({source:'synthetic curated annotations'}));
 await page.getByLabel('Perfil explícito JSON').fill(JSON.stringify(profile));
 await page.getByRole('button',{name:'Preparar snapshot',exact:true}).click();
 await page.getByText(/Preparado para entrenar: snapshot \/ new-version/).waitFor();
 if(calls.filter(c=>c.url.endsWith('/start')).length!==1)throw Error('Automatic training on preparation');
 await page.getByRole('button',{name:'Iniciar Entrenamiento Local (1 Modelo)',exact:true}).click();
 await page.getByText(/Checkpoint persistido; evaluación pendiente/).waitFor();
 starts=calls.filter(c=>c.url.endsWith('/start'));
 if(starts.length!==2||JSON.parse(starts[1].body).imported_prepared_version!=='new-version')throw Error('Wrong new version');
 await page.getByRole('button',{name:'Cerrar sesión',exact:true}).click();
 await page.getByRole('link',{name:'Iniciar sesión',exact:true}).waitFor();
 if(await page.getByLabel('Colección importada').count()!==0)throw Error('Private state survives logout');
 return {status:'passed',origin:'http://127.0.0.1:3417',transport:'all API requests intercepted, synthetic only; no real backend',existingPreparation:true,newPreparation:true,blankAnnotations:true,lockedArchitecture:true,lockedTopology:true,noAutomaticStart:true,exactPayloads:starts.map(c=>JSON.parse(c.body)),checkpointEvaluationPending:true,logoutClearsPrivateState:true,requestCount:calls.length};
}
