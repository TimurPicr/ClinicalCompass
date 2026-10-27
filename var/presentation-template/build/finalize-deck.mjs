import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {pathToFileURL} from 'node:url';
import {PresentationFile,FileBlob} from '@oai/artifact-tool';
const SKILL='/Users/user/.codex/plugins/cache/openai-primary-runtime/presentations/26.1025.11240/skills/presentations';
const WORK='/Users/user/Desktop/Code/ClinicalCompass2/var/presentation-template';
const SOURCE='/Users/user/Desktop/Clinical_Compass.pptx';
const FINAL=path.join(WORK,'output/Clinical_Compass_дополненная.pptx');
const {finalizePresentation}=await import(pathToFileURL(path.join(SKILL,'container_tools/artifact_tool_utils.mjs')).href);
const result=await finalizePresentation({
 workspaceDir:WORK,candidatePath:path.join(WORK,'build/candidate.pptx'),finalPath:FINAL,
 pythonExecutable:'/Users/user/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3',
 integrityValidatorPath:path.join(SKILL,'container_tools/inspect_presentation_package_integrity.py'),
 layoutValidatorPath:path.join(SKILL,'container_tools/inspect_presentation_layout_geometry.py'),
 requiredNativeTableOwnerSlides:[11],requiredNativeChartOwnerSlides:[],
 fontPolicy:{basis:'reference',families:['Helvetica Neue'],referencePath:SOURCE,referenceSha256:createHash('sha256').update(await fs.readFile(SOURCE)).digest('hex')},
 layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit','--require-native-table-slide','11','--folio-mode','actual_unpadded'],
 verifyArtifactToolImport:true,receiptPath:path.join(WORK,'build/final-validation.json')
});
console.log(JSON.stringify(result,null,2));
const p=await PresentationFile.importPptx(await FileBlob.load(FINAL));
await fs.mkdir(path.join(WORK,'build/final-renders'),{recursive:true});
for(let i=0;i<p.slides.items.length;i++){
 const b=await p.export({slide:p.slides.items[i],format:'png',scale:1.25});
 await fs.writeFile(path.join(WORK,'build/final-renders',`slide-${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await b.arrayBuffer()));
}
console.log('All final slides rendered.');
