import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {PresentationFile,FileBlob} from '@oai/artifact-tool';

const ROOT='/Users/user/Desktop/Code/ClinicalCompass2';
const WORK=path.join(ROOT,'var/presentation-template');
const BUILD=path.join(WORK,'build');
const SOURCE='/Users/user/Desktop/Clinical_Compass.pptx';
const FONT='Helvetica Neue';
const C={navy:'#191D2D',blue:'#315FD1',light:'#ADC5FF',white:'#FFFFFF',pale:'#F6F7FC',line:'#DFE5F2',ink:'#292D42',muted:'#758099'};
const req=createRequire(import.meta.resolve('@oai/artifact-tool'));
if(!req('skia-canvas').FontLibrary.families.includes(FONT))throw new Error('Template font unavailable');
const p=await PresentationFile.importPptx(await FileBlob.load(SOURCE));
const sourceRecords=JSON.parse('['+(await fs.readFile(path.join(BUILD,'source-inspection.ndjson'),'utf8')).trim().split('\n').join(',')+']');
const originals=sourceRecords.map(r=>p.resolve(r.id));
const noLine={style:'solid',fill:'none',width:0};
function panel(s,x,y,w,h,fill=C.white,r=30){return s.shapes.add({geometry:'roundRect',position:{left:x,top:y,width:w,height:h},fill,line:noLine,borderRadius:r});}
function text(s,value,x,y,w,h,size=26,color=C.white,bold=false,alignment='left',name){const t=s.shapes.add({geometry:'textbox',name,position:{left:x,top:y,width:w,height:h},fill:'none',line:noLine});t.text=value;t.text.style={typeface:FONT,fontFamily:FONT,fontSize:size,color,bold,alignment,insets:0,autoFit:'none',wrap:'square'};return t;}
function set(id,value){p.resolve(id).text=value;return p.resolve(id);}
function replace(id,value,size,color){const old=p.resolve(id);const frame={left:old.position.left,top:old.position.top,width:old.position.width,height:old.position.height};p.delete(id);return text(p.resolve(sourceRecords.find(r=>r.elements.some(e=>e.id===id)).id),value,frame.left,frame.top,frame.width,frame.height,size,color);}
function note(s,value,sources){s.speakerNotes.text=value+'\n\nИсточники: '+sources.join('; ');}
async function image(s,name,x,y,w,h,alt){return s.images.add({blob:new Uint8Array(await fs.readFile(path.join(WORK,'assets',name))),contentType:'image/png',alt,fit:'contain',position:{left:x,top:y,width:w,height:h},geometry:'roundRect',borderRadius:25});}

// Reuse a source slide and its header, layout, background and logo for the addition.
const metrics=originals[10].duplicate();
metrics.moveTo(10);
const copied=(await p.inspect({select:'$.slides[*]',include:['id','index','elements.id','elements.text','elements.position']})).records.find(r=>r.index===10);
for(const e of copied.elements){if(e.text==='Предложения')set(e.id,'Функции и время обработки');if(!e.text&&e.position?.top===108.5)p.delete(e.id);}
// Retain existing source slide objects and change only the local header titles.
set('sh/do761ova','Путь пациента: подключение');
set('sh/m583eds3','Путь пациента: наблюдение');
set('sh/apc3q143','Спасибо за внимание!');

// Correct repeated numbers in the template and align the chat header with the others.
for(const e of sourceRecords[9].elements){
 if(e.position?.top<110){const o=p.resolve(e.id);o.position={...o.position,top:o.position.top-11};}
}
const numbered=(await p.inspect({select:'$.slides[*]',include:['id','index','elements.id','elements.text','elements.position']})).records;
for(const r of numbered){
 const folio=r.elements.find(e=>/^\d+$/.test(e.text||'')&&e.position?.top<110&&e.position?.left>1100);
 if(folio){const t=set(folio.id,String(r.index+1));t.position={left:1164,top:38.99,width:60,height:38.02};t.text.style={fontSize:32.67,typeface:FONT,color:C.ink,bold:true,alignment:'center',insets:0,autoFit:'none'};}
 else text(p.resolve(r.id),String(r.index+1),1164,669,60,30,21,C.light,false,'right','slide-number');
}

// 1. Keep the minimal title and team exactly as the supplied template.
note(originals[0],'Clinical Compass — рабочий прототип для наблюдения между приёмами. В презентации используются синтетические истории. Модель готовит материал для проверки врачом. Клиническая эффективность и экономия рабочего времени врача ещё не измерены.',['README.md','docs/demo-scenarios.md']);

// 2. Complete the stated problem without inventing results of physician research.
{
 const s=originals[1];
 const t=set('sh/69wbilcj','Данные пациента разрознены.\nВремя приёма ограничено.');t.position={left:56,top:128,width:1168,height:130};
 text(s,'Перед повторным приёмом',56,336,550,48,31,C.light,true);
 text(s,'Врач сопоставляет дневник,\nанкеты, назначения и сообщения.',56,407,550,120,32);
 text(s,'Между приёмами',698,336,526,48,31,C.light,true);
 text(s,'Нужно заметить ухудшение\nи понять причину сигнала.',698,407,526,120,32);
 text(s,'Рабочая гипотеза проекта. Затраты времени врача ещё предстоит измерить.',60,672,1160,30,19,C.light);
 note(s,'Проблема сформулирована как рабочая гипотеза проекта. Исследований трудозатрат врачей, подтверждённых сэкономленных часов или клинических результатов в проекте нет. Приложение связывает дневник, анкеты, медицинскую карту, назначения и переписку.',['README.md','app/backend/patients.py','docs/demo-scenarios.md']);
}
// 3. Fill the source blank slide using the template's existing visual language.
{
 const s=originals[2];p.delete('sh/a10b6p03');
 text(s,'Единая история наблюдения\nдля врача и пациента',56,129,1168,132,49);
 panel(s,56,309,1168,267);
 text(s,'Сбор данных',86,343,510,50,34,C.ink,true);
 text(s,'Дневник, анкеты, назначения\nи документы пациента',86,413,510,94,29,C.muted);
 text(s,'Подготовка к приёму',682,343,510,50,34,C.ink,true);
 text(s,'Динамика, сводка состояния\nи основания сигнала',682,413,510,94,29,C.muted);
 text(s,'Врач проверяет сведения и выбирает действия.',60,629,1150,55,33,C.light);
 note(s,'Идея решения — общая история наблюдения и отдельные основания для врачебной оценки. Подтверждённая медицинская карта отделена от сведений со слов пациента. Назначения ведёт врач, их изменения сохраняются в версиях. Модель не выбирает лечение и не меняет назначения.',['README.md','app/backend/patients.py','app/backend/medications.py','app/backend/ai/service.py']);
}
// 4. An ordinary numbered process, not an added memorable gimmick.
{
 const s=originals[3];p.delete('sh/cnyp8jep');
 text(s,'Подключение к наблюдению',56,130,1168,78,49);
 panel(s,56,242,1168,356);
 const steps=[['1','Приглашение','Врач передаёт персональную ссылку\nна регистрацию'],['2','Сведения пациента','Пациент заполняет профиль\nи добавляет документы'],['3','План наблюдения','Врач подтверждает карту\nи назначает дневник и анкеты']];
 steps.forEach(([n,head,body],i)=>{const y=269+i*110;text(s,n,88,y+3,62,62,44,C.blue);text(s,head,177,y+4,405,55,31,C.ink,true);text(s,body,632,y+4,552,86,27,C.muted);});
 text(s,'Подтверждённые данные отделены от сведений со слов пациента.',60,644,1150,50,27,C.light);
 note(s,'Врач создаёт приглашение и самостоятельно передаёт пациенту ссылку. После регистрации пациент прикрепляется к врачу. Пациент заполняет неподтверждённые сведения о себе и может загрузить документы. Врач проверяет сведения, подтверждает медицинскую карту и задаёт план наблюдения. Документ не перезаписывает подтверждённую карту автоматически.',['README.md','app/backend/auth.py','app/backend/patients.py','app/backend/documents.py','app/backend/questionnaire_routes.py','app/backend/diary.py']);
}
// 5. Actual patient form. No record was submitted to produce this screenshot.
{
 const s=originals[4];p.delete('sh/76hk7ito');
 text(s,'Записи и ответы между приёмами',56,130,1168,78,49);
 await image(s,'patient-diary-form.png',56,224,690,465,'Исходная форма дневника в кабинете синтетической пациентки Анны');
 text(s,'Самочувствие',800,234,424,46,31,C.white,true);
 text(s,'Пять показателей\nи комментарий пациента',800,293,424,83,26,C.light);
 text(s,'Приём лекарства',800,392,424,46,31,C.white,true);
 text(s,'Фактический приём\nили явный пропуск',800,451,424,78,26,C.light);
 text(s,'Анкеты',800,548,424,46,31,C.white,true);
 text(s,'Ответы по плану врача',800,607,424,50,26,C.light);
 text(s,'Форма ввода, значения по умолчанию',800,680,424,26,17,C.light);
 note(s,'На слайде фактический интерфейс формы дневника. Показаны начальные значения формы, запись для снимка не сохранялась. Дневник содержит настроение, тревогу, качество сна, энергию и самочувствие по шкалам от 0 до 10 и свободный комментарий. Оценка сна означает качество, не часы. Фактический приём и явный пропуск относятся к разделу назначений. Отсутствие дневниковой записи не доказывает пропуск лекарства.',['var/presentation-template/assets/patient-capture-manifest.json','app/backend/diary.py','app/backend/medications.py','app/backend/questionnaires.py']);
}
// 6. Preserve the supplied summary screenshot and correct the time claim.
{
 const s=originals[5];
 const intro=replace('sh/wfahsbih','История пациента и динамика состояния\nдля подготовки к повторному приёму',49,C.white);
 intro.position={left:56,top:139.92,width:1168,height:140};
 const metric=set('sh/xg3ylgj2','Медиана локального замера: 26,4 с');metric.text.style={fontSize:39.67,typeface:FONT,color:C.light,alignment:'right',insets:0,autoFit:'none'};
 text(s,'3 сценария, без очереди и наполненной базы источников. Каждую сводку проверяет врач.',60,684,1160,25,18,C.light);
 note(s,'Скриншот — ранее сохранённая сводка синтетической пациентки Анны. Число 26,4 с — медиана трёх реальных попыток создания описания на Apple M3 Pro с 18 GiB RAM. Это не среднее и не время получения гарантированно правильного описания. Замер включает подготовку контекста, загрузку моделей, генерацию, фиксацию/отмену в изолированной SQLite и автоматическую оценочную рубрику, исключает ожидание очереди и поиск по наполненной базе источников. Основная модель qwen3:4b-q4_K_M, векторная qwen3-embedding:0.6b. Проверки содержания прошли два из трёх ответов. Врачебная оценка качества не проводилась.',['var/presentation/benchmark.json','scripts/benchmark_presentation.py','app/backend/ai/service.py']);
}
// 7. Keep the template's original screenshot, crop and proportions.
{
 const s=originals[6];
 text(s,'Сначала пациенты с более высоким приоритетом',56,119,1168,47,32);
 text(s,'Цвет статуса не является диагнозом. На экране синтетические истории.',60,668,1160,30,20,C.light);
 note(s,'Список упорядочен по приоритету наблюдения, возле статуса показано его активное основание. Врач открывает подробную карту пациента. Изображение из пользовательского шаблона сохранено без замены и кадрирования. Все четыре истории синтетические.',['app/backend/patients.py','app/backend/monitoring.py','docs/demo-scenarios.md']);
}
// 8. Keep the supplied graph as evidence of the current application.
{
 const s=originals[7];
 text(s,'Изменения самочувствия по дням',56,128,1168,55,39);
 text(s,'21 день наблюдений',60,633,530,45,29);
 text(s,'5 показателей по шкале от 0 до 10',623,637,601,42,27,C.light,false,'right');
 text(s,'Сон в дневнике означает качество сна. Синтетический пример.',60,686,1160,25,18,C.light);
 note(s,'График из исходного шаблона показывает 21 ежедневную запись синтетического Андрея Авиандрова. Пять шкал от 0 до 10. У тревоги большее значение означает более выраженную тревогу, у остальных показателей — лучшее самочувствие. Сон означает качество сна. График не доказывает эффект лечения или клиническую эффективность приложения.',['docs/demo-scenarios.md','app/backend/diary.py']);
}
// 9. Correct the source's overbroad promise about diary free text and immediacy.
{
 const s=originals[8];
 text(s,'Правила формируют сигнал до подготовки сводки',56,130,1168,55,37);
 const left=p.resolve('sh/m5kby5kj');const lf={left:left.position.left,top:left.position.top,width:left.position.width};p.delete('sh/m5kby5kj');
 text(s,'Положительный ответ на критический\nпункт анкеты.\n\nСигнал формируется при сохранении\nответа.',lf.left,lf.top,lf.width,190,25,C.muted);
 const right=p.resolve('sh/batsval0');const rf={left:right.position.left,top:right.position.top,width:right.position.width};p.delete('sh/batsval0');
 text(s,'Повышенные баллы анкеты\nПовторные явные пропуски приёма\nСообщения о нежелательных явлениях',rf.left,rf.top,rf.width,170,25,C.muted);
 text(s,'Критический сигнал сохраняется до рассмотрения врачом.',60,640,1160,70,29,C.light);
 note(s,'Красный детерминированный сигнал формируется при положительном ответе на пункт 9 анкеты депрессии. Он возникает при сохранении ответа и не зависит от генерации сводки. Приложение не имеет мгновенного клинического правила распознавания всех критических высказываний свободного текста дневника. Критический сигнал не снимается новой низкой оценкой или готовностью описания. Некритические сигналы могут разрешаться автоматически при исчезновении условия. Повторные явные пропуски лекарства и сообщения о нежелательных явлениях — отдельные основания внимания. Причинность нежелательного явления не доказана фактом сообщения.',['docs/clinical-rules.md','app/backend/monitoring.py','tests/test_monitoring_scenarios.py']);
}
// 10. Preserve the source chat screenshot and add its physician-facing use.
{
 const s=originals[9];
 text(s,'Врач видит диалоги со своими пациентами в одном разделе',56,130,1168,51,32);
 text(s,'Сообщения и вложения сохраняются в истории.',60,637,1160,47,31,C.light);
 text(s,'Переписка доступна после восстановления связи.',60,684,1160,25,20,C.light);
 note(s,'В кабинете врача есть общий список всех его диалогов. Сообщения и вложения сохраняются на сервере. Доставка использует постоянное соединение, повторное подключение и резервное обновление истории. История остаётся доступна после восстановления соединения. Изображение исходного шаблона сохранено. Переписка не обеспечивает экстренную помощь или гарантированный немедленный ответ врача.',['app/backend/chat.py','app/frontend/src/pages/Messages.jsx','docs/chat-verification.md']);
}
// 11. The only added slide: an editable capability/benefit/measurement table.
{
 const report=JSON.parse(await fs.readFile(path.join(ROOT,'var/presentation/benchmark.json'),'utf8'));
 const f=(n)=>n.toLocaleString('ru-RU',{minimumFractionDigits:1,maximumFractionDigits:1});
 text(metrics,'Результаты локального замера',56,130,1168,57,39);
 panel(metrics,56,207,1168,373);
 const r=report.api_reads.operations.map(x=>x.timings.median_seconds*1000);
 const values=[['Возможность','Польза для врача','Медиана'],['Карта и назначения','Анамнез и лечение в одной истории',`${f(r[0])} мс\nполучение карты`],['Дневник и анкеты','Динамика состояния по датам',`${f(r[1])} мс\nполучение дневника`],['Переписка','История обсуждений с пациентом',`${f(r[2])} мс\nполучение истории`],['Контроль риска','Правила и очередь описания',`${f(report.postgres_diary.timings.median_seconds*1000)} мс\nоперация в базе*`],['Сводка состояния','Материал для разбора перед приёмом',`${f(report.ai_summary.all_attempts.median_seconds)} с\nпопытка создания**`]];
 const t=metrics.tables.add({rows:6,columns:3,left:66,top:218,width:1148,height:334,columnWidths:[260,558,330],values});
 t.styleOptions={headerRow:false,bandedRows:false};
 t.cells.block({row:0,column:0,rowCount:6,columnCount:3}).assign({fill:C.white,textStyle:{typeface:FONT,fontFamily:FONT,fontSize:22,color:C.ink},margins:{left:18,right:16,top:4,bottom:4},anchor:'center'});
 t.borders.assign({style:'solid',fill:C.line,width:0.7});t.rows[0].height=44;
 for(let i=1;i<6;i++){t.rows[i].height=58;t.getCell(i,2).text.style={typeface:FONT,fontFamily:FONT,fontSize:20,color:C.blue,bold:true};}
 for(let j=0;j<3;j++){t.getCell(0,j).fill=C.pale;t.getCell(0,j).text.style={typeface:FONT,fontFamily:FONT,fontSize:22,color:C.muted,bold:true};}
 text(metrics,'Apple M3 Pro, 18 ГБ. По 10 повторов быстрых операций без отрисовки, 3 попытки сводки.',60,605,1160,29,19,C.light);
 text(metrics,'* Без окончательной фиксации в базе. ** Без очереди и наполненной базы источников.',60,638,1160,29,19,C.light);
 text(metrics,'Автоматические проверки содержания прошли 2 из 3 описаний. Врачебная оценка ещё впереди.',60,671,1160,29,19,C.light);
 note(metrics,'Реальные локальные измерения 27.10.2026. Apple M3 Pro, 12 ядер, 18 GiB RAM, Ollama 0.40.11. Десять последовательных HTTP GET на каждую операцию с постоянным соединением, без авторизации и отрисовки. Обработка новой дневниковой записи: фактические insert/flush, производственные правила и очередь в PostgreSQL 16.15, без commit/HTTP. Временные изменения отменены. Три сценария модели: 25,807–27,005 с, медиана 26,400 с, включая модельную загрузку, контекст, создание, фиксацию/отмену в изолированной SQLite и автоматическую оценочную рубрику. Без очереди и наполненной базы источников. Все три ответа соответствовали схеме, два прошли автоматические проверки содержания. Один ответ добавил отсутствующую шкалу тревоги. Это не клиническая оценка точности, не нагрузочное испытание и не измерение экономии времени врача.',['var/presentation/benchmark.json','scripts/benchmark_presentation.py']);
}
// 12. Fill the original proposals slide with future work, not invented outcomes.
{
 const s=originals[10];p.delete('sh/zmxwf29s');
 text(s,'Следующий этап: оценка с врачами',56,130,1168,75,49);
 text(s,'Качество описаний',56,263,550,51,33,C.light,true);
 text(s,'Проверить факты, объяснения риска\nи полезность сводки перед приёмом.',56,337,550,123,30);
 text(s,'Работа врача',698,263,526,51,33,C.light,true);
 text(s,'Время подготовки к приёму\nи число лишних сигналов.',698,337,526,123,30);
 panel(s,56,504,1168,119);
 text(s,'201 программная проверка',84,526,540,51,35,C.blue);
 text(s,'187 серверной части и 14 интерфейса',84,581,540,29,19,C.muted);
 text(s,'Клиническая проверка\nпока не проводилась',700,526,480,80,29,C.ink);
 text(s,'Рабочий прототип на 4 синтетических историях по 21 дню наблюдений.',60,671,1160,29,20,C.light);
 note(s,'Предложенные действия — следующий этап, не уже полученные результаты. Следует согласовать с врачами выборку и критерии проверки фактов, оснований риска и полезности описаний. Сравнение времени подготовки к приёму и количества лишних сигналов пока не проводилось. 201 — сумма 187 серверных и 14 интерфейсных тестов из документированного прогона 26.10.2026, не клиническая точность. Четыре синтетические истории имеют по 21 ежедневной записи.',['docs/chat-verification.md','docs/demo-scenarios.md','var/presentation/benchmark.json']);
}
// 13. Retain the supplied closing composition and the team name.
note(originals[11],'Команда Ф(Э)ФМ. Clinical Compass — рабочий прототип на синтетических данных. Врач проверяет описания и принимает клинические решения.',['README.md','docs/demo-scenarios.md']);

await fs.mkdir(path.join(BUILD,'renders'),{recursive:true});
for(let i=0;i<p.slides.items.length;i++){
 const blob=await p.export({slide:p.slides.items[i],format:'png',scale:1.25});
 await fs.writeFile(path.join(BUILD,'renders',`slide-${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await blob.arrayBuffer()));
 console.log('Rendered',i+1);
}
await (await PresentationFile.exportPptx(p)).save(path.join(BUILD,'candidate.pptx'));
await fs.writeFile(path.join(BUILD,'edited-inspection.ndjson'),(await p.inspect({select:'$.slides[*]',include:['id','index','layout','title','elements.id','elements.kind','elements.text','elements.position','elements.style','notes.text']})).ndjson);
console.log('Edited candidate exported.');
