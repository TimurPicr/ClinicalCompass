import fs from 'node:fs/promises';
import path from 'node:path';
import {PresentationFile,FileBlob} from '@oai/artifact-tool';
const WORK='/Users/user/Desktop/Code/ClinicalCompass2/var/presentation-template/build';
const p=await PresentationFile.importPptx(await FileBlob.load('/Users/user/Desktop/Clinical_Compass.pptx'));
const inspection=await p.inspect({select:'$.slides[*]',include:['id','index','layout','title','elements.id','elements.kind','elements.text','elements.alt','elements.position','elements.style','notes.text']});
await fs.writeFile(path.join(WORK,'source-inspection.ndjson'),inspection.ndjson);
console.log(JSON.stringify({slides:p.slides.items.length,masters:p.masters.items.map(m=>({id:m.id,name:m.name})),layouts:p.layouts.items.map(m=>({id:m.id,name:m.name,placeholders:m.placeholders.summary()}))},null,2));
for(let i=0;i<p.slides.items.length;i++){
 const png=await p.export({slide:p.slides.items[i],format:'png',scale:1.25});
 await fs.writeFile(path.join(WORK,'source-renders',`slide-${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await png.arrayBuffer()));
 const layout=await p.slides.items[i].export({format:'layout',detail:'full'});
 await fs.writeFile(path.join(WORK,'source-renders',`slide-${String(i+1).padStart(2,'0')}.layout.json`),await layout.text());
}
console.log('Source slides rendered.');
