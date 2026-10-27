import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {PresentationFile, FileBlob} from '@oai/artifact-tool';

const SKILL='/Users/user/.codex/plugins/cache/openai-primary-runtime/presentations/26.1025.11240/skills/presentations';
const WORK='/Users/user/Desktop/Code/ClinicalCompass2/var/presentation';
const {finalizePresentation}=await import(pathToFileURL(path.join(SKILL,'container_tools/artifact_tool_utils.mjs')).href);
const result=await finalizePresentation({
 workspaceDir:WORK,
 candidatePath:path.join(WORK,'build/candidate.pptx'),
 finalPath:path.join(WORK,'output/Clinical_Compass.pptx'),
 pythonExecutable:'/Users/user/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3',
 integrityValidatorPath:path.join(SKILL,'container_tools/inspect_presentation_package_integrity.py'),
 layoutValidatorPath:path.join(SKILL,'container_tools/inspect_presentation_layout_geometry.py'),
 explicitTotalSlideCount:10,
 requiredNativeTableOwnerSlides:[7],
 requiredNativeChartOwnerSlides:[],
 fontPolicy:{basis:'design',families:['Helvetica Neue']},
 layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit','--require-native-table-slide','7'],
 verifyArtifactToolImport:true,
 receiptPath:path.join(WORK,'build/final-validation.json'),
});
console.log(JSON.stringify(result,null,2));
const finalDeck=await PresentationFile.importPptx(await FileBlob.load(path.join(WORK,'output/Clinical_Compass.pptx')));
await fs.mkdir(path.join(WORK,'build/final-renders'),{recursive:true});
for(let i=0;i<finalDeck.slides.items.length;i++){
 const png=await finalDeck.export({slide:finalDeck.slides.items[i],format:'png',scale:1.5});
 await fs.writeFile(path.join(WORK,'build/final-renders',`slide-${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await png.arrayBuffer()));
}
console.log('All final slides rendered.');
