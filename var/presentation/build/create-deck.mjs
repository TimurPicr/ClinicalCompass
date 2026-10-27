import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {Presentation, PresentationFile} from '@oai/artifact-tool';

const ROOT='/Users/user/Desktop/Code/ClinicalCompass2';
const WORK=path.join(ROOT,'var/presentation');
const BUILD=path.join(WORK,'build');
const ASSETS=path.join(WORK,'assets');
const C={navy:'#191d2d',blue:'#315fd1',light:'#adc5ff',white:'#ffffff',pale:'#f6f7fc',line:'#dfe5f2',ink:'#292d42',muted:'#758099',red:'#bf4842',redBg:'#fbeae7',amber:'#95671d',amberBg:'#fcf2df',grayBg:'#edf0f7'};
const FONT='Helvetica Neue';
const req=createRequire(import.meta.resolve('@oai/artifact-tool'));
const {FontLibrary}=req('skia-canvas');
if(!FontLibrary.families.includes(FONT)) throw new Error('Chosen font unavailable');
const p=Presentation.create({slideSize:{width:1280,height:720}});
p.theme.defaultFont=FONT;
const logo=await fs.readFile(path.join(ROOT,'app/frontend/public/icon.svg'),'utf8');
const benchmark=JSON.parse(await fs.readFile(path.join(WORK,'benchmark.json'),'utf8'));
const fmt=(n,d=1)=>n.toLocaleString('ru-RU',{minimumFractionDigits:d,maximumFractionDigits:d});
const none={style:'solid',fill:'none',width:0};
function shape(s,x,y,w,h,fill,r=0,line=none){return s.shapes.add({geometry:r?'roundRect':'rect',position:{left:x,top:y,width:w,height:h},fill,line,borderRadius:r||undefined});}
function text(s,str,x,y,w,h,size=26,color=C.ink,bold=false,extra={}){
 const t=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:none});
 t.text=str;t.text.style={fontFamily:FONT,typeface:FONT,fontSize:size,color,bold,autoFit:'none',wrap:'square',insets:0,...extra};return t;
}
function pill(s,str,x,y,w,fill=C.pale,color=C.muted){shape(s,x,y,w,34,fill,17);text(s,str,x+14,y+5,w-28,25,18,color,false);}
function header(s,section,num){
 shape(s,40,26,1200,66,C.white,33);
 s.images.add({svg:logo,alt:'Знак Clinical Compass',position:{left:55,top:37,width:44,height:44}});
 text(s,'Clinical Compass',112,43,340,38,26,C.ink,true);
 text(s,section,760,45,420,30,20,C.muted,false,{alignment:'right'});
 text(s,String(num).padStart(2,'0'),1188,45,30,26,18,C.muted,false,{alignment:'right'});
}
function slide(section,title,num,subtitle){const s=p.slides.add();s.background.fill=C.navy;header(s,section,num);text(s,title,56,125,1168,100,49,C.white,false);if(subtitle)text(s,subtitle,58,219,1160,45,23,C.light);return s;}
function notes(s,body,sources){s.speakerNotes.text=body+'\n\nИсточники: '+sources.join('; ');}
async function image(s,name,x,y,w,h,alt,r=20,fit='contain'){
 const im=s.images.add({blob:new Uint8Array(await fs.readFile(path.join(ASSETS,name))),contentType:'image/png',alt,fit,position:{left:x,top:y,width:w,height:h},geometry:r?'roundRect':'rect',borderRadius:r||undefined});
 if(name==='diary-chart.png') im.crop={left:0,top:0.012,right:0,bottom:0.012};
}

// 1. The product promise uses the same dark canvas and capsule header as the site.
{
 const s=p.slides.add();s.background.fill=C.navy;header(s,'Решение кейс-чемпионата',1);
 text(s,'Наблюдение',56,151,1168,100,86,C.white);
 text(s,'между приёмами',56,245,1168,104,86,C.light);
 text(s,'Дневник пациента, сигналы риска и описание\nсостояния в одном кабинете врача.',60,384,1030,84,31,C.white);
 shape(s,56,522,1168,128,C.white,30);
 text(s,'Основная идея',84,545,250,35,23,C.muted);
 text(s,'Собрать историю и выделить изменения,\nкоторые врачу стоит проверить.',350,540,820,80,31,C.ink);
 notes(s,'Clinical Compass — прототип сопровождения пациентов между приёмами. Данные дневника, стандартизированных анкет, анамнеза и лечения доступны в одном кабинете. Описание искусственного интеллекта является материалом для проверки врачом. Клиническая эффективность и экономия времени врача не измерены.',['README.md','docs/demo-scenarios.md']);
}
// 2. Clearly framed design hypotheses, not invented research findings.
{
 const s=slide('Задача врача','Перед решением нужно собрать историю',2);
 shape(s,56,248,1168,390,C.white,30);
 const rows=[
 ['01','Разные источники','Дневник, анкеты, документы и назначения\nприходится сопоставлять.'],
 ['02','Изменения между приёмами','Нужны основания, чтобы определить,\nкому требуется внимание раньше.'],
 ['03','Неоднозначные отметки','Отсутствие записи и явный пропуск\nлекарства означают разное.']
 ];
 rows.forEach(([n,head,body],i)=>{const y=272+i*118;text(s,n,84,y+10,65,55,34,C.blue);text(s,head,172,y+5,420,48,29,C.ink,true);text(s,body,646,y+5,530,88,25,C.muted);if(i<2)shape(s,84,y+104,1108,1,C.line);});
 text(s,'Рабочие гипотезы проекта. Исследование затрат времени врача ещё предстоит.',60,664,1150,28,18,C.light);
 notes(s,'Проблемы сформулированы как гипотезы проекта, а не результаты пользовательского или клинического исследования. Решение не имеет подтверждённого численного эффекта на затраты времени врача.',['README.md','docs/demo-scenarios.md']);
}
// 3. An editable explanatory diagram, with a human clinical decision owner.
{
 const s=slide('Основная идея','Одна история от записи до приёма',3);
 shape(s,56,247,1168,300,C.white,30);
 const data=[['1','Пациент','Ведёт дневник\nи отвечает на анкеты'],['2','Карта','Анамнез, назначения,\nанкеты и документы'],['3','Система','Проверяет правила\nи описывает динамику'],['4','Врач','Проверяет основания\nи выбирает действия']];
 data.forEach(([n,head,body],i)=>{const x=84+i*281;shape(s,x,276,44,44,C.blue,22);text(s,n,x,282,44,35,23,C.white,true,{alignment:'center'});text(s,head,x,343,250,45,31,C.ink,true);text(s,body,x,407,245,80,24,C.muted);if(i<3)shape(s,x+248,298,26,2,C.line);});
 text(s,'Искусственный интеллект готовит материал к разбору.\nКлиническое решение принимает врач.',60,586,1160,88,32,C.light);
 notes(s,'Схема отражает текущие роли. Подтверждённая врачом медицинская карта отделена от неподтверждённых сведений пациента. Документы проходят рассмотрение врачом. Модель не изменяет назначения.',['app/backend/clinical.py','app/backend/ai/service.py','app/frontend/src/App.jsx']);
}
// 4. Real screenshot, with the source scenario stated visibly.
{
 const s=slide('Кабинет врача','Кому нужно внимание сегодня',4);
 text(s,'Приоритет и причина сигнала в одном списке. Синтетические истории.',60,195,1160,29,22,C.light);
 await image(s,'dashboard-table.png',100,230,1080,460,'Фактический список четырёх синтетических пациентов с причинами приоритета',20);

 notes(s,'Снимок текущего сайта от 27.10.2026. Список врача doctor.realistic-v2 содержит четыре синтетические истории. Цвет статуса не является диагнозом. Причины формируются независимо от того, завершила ли модель подготовку описания.',['var/presentation/assets/capture-manifest.json','app/backend/clinical.py','docs/demo-scenarios.md']);
}
// 5. A different view and a large, readable graph preserve product evidence.
{
 const s=slide('Наблюдение пациента','Динамика вместо отдельных отметок',5);
 shape(s,56,246,1168,390,C.white,30);
 await image(s,'diary-chart.png',78,277,1108,323,'График двадцати одной ежедневной записи Андрея Авиандрова',30);
 text(s,'21 день наблюдений',60,661,320,30,23,C.white);
 text(s,'Настроение, тревога, сон, энергия и самочувствие',430,661,780,30,23,C.light,false,{alignment:'right'});
 notes(s,'График фактических синтетических записей Андрея Авиандрова, не данные реального пациента. В дневнике пять шкал от 0 до 10. Показатель сна означает качество, не количество часов. У тревоги большее значение означает большее неблагополучие, у остальных шкал — лучшее состояние. Анкеты тревоги и депрессии имеют фиксированные схемы и отдельные результаты.',['var/presentation/assets/capture-manifest.json','docs/demo-scenarios.md','app/backend/diary.py']);
}
// 6. The saved description is shown alongside a concise explanation of its role.
{
 const s=slide('Описание состояния','Описание с опорой на историю',6);
 shape(s,56,245,1168,397,C.white,30);
 const anna=await fs.stat(path.join(ASSETS,'anna-summary.png')).then(()=>true).catch(()=>false);
 await image(s,anna?'anna-summary.png':'ai-summary.png',78,270,1124,235,'Ранее подготовленное описание состояния синтетического пациента',18);
 text(s,'Динамика и контекст',86,550,353,44,27,C.ink,true);
 text(s,'Основания риска',470,550,330,44,27,C.ink,true);
 pill(s,'Локальная модель',860,548,300,C.grayBg,C.blue);
 text(s,'Каждое описание требует проверки врачом.',60,663,1140,30,23,C.light);
 notes(s,'Визуал — ранее сохранённое описание синтетической истории, а не результат сегодняшнего замера. Модель получает ограниченное окно дневника и анкет, подтверждённую карту, историю назначений и существующие сигналы. Структура ответа, ссылки на разрешённые факты и обязательное покрытие известных критических сигналов проверяются программно. Это не гарантирует корректность всех утверждений. В сегодняшних трёх попытках одна содержала неверно указанную шкалу, что обнаружила дополнительная оценочная рубрика. Описание формируется локально, данные не отправляются внешней языковой модели.',['app/backend/ai/service.py','app/backend/ai/ollama.py','var/presentation/benchmark.json','var/presentation/assets/capture-manifest.json']);
}
// 7. Required native, editable table. Metrics have deliberately narrow labels.
{
 const s=slide('Возможности и метрики','Функции, польза и измеренное время',7);
 const read=benchmark.api_reads.operations.map(x=>x.timings.median_seconds*1000);
 const rows=[
 ['Функция','Польза для врача','Медиана замера'],
 ['Карта и назначения','Анамнез и лечение в одной истории',`${fmt(read[0])} мс\nполучение карты`],
 ['Дневник и анкеты','Динамика состояния по датам',`${fmt(read[1])} мс\nполучение дневника`],
 ['Сообщения','История обсуждений с пациентом',`${fmt(read[2])} мс\nполучение истории`],
 ['Контроль риска','Проверка записи и очередь описания',`${fmt(benchmark.postgres_diary.timings.median_seconds*1000)} мс\nоперация в базе*`],
 ['Описание','Материал для проверки перед приёмом',`${fmt(benchmark.ai_summary.all_attempts.median_seconds)} с\nпопытка создания**`]
 ];
 shape(s,56,237,1168,373,C.white,26);
 const t=s.tables.add({rows:6,columns:3,left:66,top:247,width:1148,height:334,columnWidths:[250,568,330],values:rows});
 t.styleOptions={headerRow:false,bandedRows:false};
 t.cells.block({row:0,column:0,rowCount:6,columnCount:3}).assign({fill:C.white,textStyle:{fontFamily:FONT,typeface:FONT,fontSize:22,color:C.ink},margins:{left:18,right:16,top:4,bottom:4},anchor:'center'});
 t.borders.assign({style:'solid',fill:C.line,width:0.7});
 t.rows[0].height=44;
 for(let r=1;r<6;r++)t.rows[r].height=58;
 for(let c=0;c<3;c++){t.getCell(0,c).fill=C.pale;t.getCell(0,c).text.style={fontFamily:FONT,typeface:FONT,fontSize:21,color:C.muted,bold:true};}
 for(let r=1;r<6;r++) t.getCell(r,2).text.style={fontFamily:FONT,typeface:FONT,fontSize:20,color:C.blue,bold:true};
 text(s,'Apple M3 Pro, 18 ГБ. По 10 повторов ответа сервера без отрисовки, 3 попытки описания.',60,622,1150,28,18,C.light);
 text(s,'* Без окончательной фиксации в базе. ** Без ожидания очереди и поиска по базе знаний.',60,650,1150,25,18,C.light);
 text(s,'Автоматические проверки содержания прошли 2 из 3 описаний. Это не врачебная оценка.',60,676,1150,25,18,C.light);
 notes(s,`Измерено 27.10.2026 по московскому времени. Реальные вызовы на Apple M3 Pro, 12 ядер, 18 GiB RAM, macOS 26.6.2. Локальная модель qwen3:4b-q4_K_M, модель векторного представления qwen3-embedding:0.6b, Ollama 0.40.11. Три разных синтетических сценария, время попытки создания описания: ${benchmark.ai_summary.all_attempts.min_seconds.toFixed(3)}–${benchmark.ai_summary.all_attempts.max_seconds.toFixed(3)} с, медиана ${benchmark.ai_summary.all_attempts.median_seconds.toFixed(3)} с. Включены загрузка модели, подготовка контекста, генерация, фиксация или отмена результата в изолированной SQLite и автоматическая оценочная рубрика. Ожидание очереди, распознавание документов и поиск по наполненной базе знаний исключены. Все три ответа прошли схему, два прошли автоматическую содержательную рубрику. В одном ответе перепутана/добавлена шкала тревоги при наличии только шкалы депрессии; это не было заблокировано основной схемой. Это не оценка клинической точности. Быстрые операции: десять последовательных реальных HTTP GET на операцию с постоянным соединением и локальной базой, авторизация и отрисовка исключены. Обработка записи: фактические insert/flush, производственные правила и постановка в очередь в PostgreSQL 16.15, без commit/HTTP, все временные изменения отменены. Времена не являются обещанием производительности при сетевой или массовой нагрузке.`,['scripts/benchmark_presentation.py','var/presentation/benchmark.json']);
}
// 8. Deterministic signals and model explanations are explicit separate stages.
{
 const s=slide('Сигналы риска','Сигнал риска не ждёт модель',8);
 shape(s,56,247,1168,380,C.white,30);
 pill(s,'Срочная оценка',86,277,210,C.redBg,C.red);
 text(s,'Критический ответ в анкете',86,334,520,49,31,C.ink,true);
 text(s,'Сигнал сохраняется до рассмотрения\nврачом, даже если описание не готово.',86,401,530,86,25,C.muted);
 shape(s,645,280,1,304,C.line);
 pill(s,'Внимание',686,277,167,C.amberBg,C.amber);
 text(s,'Основание доступно врачу',686,334,485,49,31,C.ink,true);
 text(s,'Повышенные баллы анкеты,\nявные пропуски приёма лекарства\nили сообщения о нежелательных явлениях.',686,401,482,125,25,C.muted);
 text(s,'Правила определяют сигнал. Модель помогает разобрать контекст.',60,662,1140,30,24,C.light);
 notes(s,'Это описание действующего программного поведения, не медицинская рекомендация и не доказательство клинической эффективности. Положительный ответ q9 анкеты депрессии формирует красный сигнал. Повышенные суммарные баллы анкет, операционные пропуски и другие заранее заданные правила могут формировать жёлтые сигналы. Наличие пропуска записи не доказывает пропуск лекарственного приёма. Критический сигнал не снимается новой низкой оценкой или готовностью описания. Некритические сигналы могут разрешаться автоматически при исчезновении условия. Врач рассматривает и закрывает сигнал.',['app/backend/monitoring.py','tests/test_clinical.py','docs/clinical-rules.md']);
}
// 9. Screenshot of the actual messaging feature, no seeded test messages added.
{
 const s=slide('Связь с пациентом','Переписка рядом с историей лечения',9);
 const hasChat=await fs.stat(path.join(ASSETS,'messages.png')).then(()=>true).catch(()=>false);
 if(hasChat){const im=s.images.add({blob:new Uint8Array(await fs.readFile(path.join(ASSETS,'messages.png'))),contentType:'image/png',alt:'Два исходных сообщения врача и синтетической пациентки Анны',fit:'contain',position:{left:56,top:234,width:1168,height:388},crop:{left:0,top:0,right:0,bottom:0.4},geometry:'roundRect',borderRadius:20});}
 else {await image(s,'record.png',56,244,770,380,'Медицинская карта синтетического пациента',20);text(s,'Все диалоги\nв кабинете врача',866,277,330,90,32,C.white);text(s,'Текст и вложения\nсохраняются в истории.',866,402,330,100,26,C.light);}
 text(s,'Чаты с пациентами',60,641,530,34,27,C.white);
 text(s,'Сообщения и вложения сохраняются',60,679,590,28,22,C.light);
 text(s,'Медицинские источники',700,641,510,34,27,C.white);
 text(s,'Поиск, ссылки и проверка документов',700,679,510,28,22,C.light);
 notes(s,'Врач видит общий список диалогов со своими пациентами и выбранную переписку. Сообщения и вложения сохраняются сервером. Доставка использует постоянное соединение, повторное подключение и резервное обновление истории. Проверена переписка в обе стороны и восстановление после сбоев. Это не канал гарантированной экстренной помощи. В приложении также есть библиотека медицинских источников с поиском и ссылками на страницы, загрузка документов с проверкой извлечённых сведений врачом, версии назначений.',['docs/chat-verification.md','app/frontend/src/pages/Chat.jsx','app/backend/chat.py','var/presentation/assets/capture-manifest.json']);
}
// 10. Technical readiness and the uncompleted clinical work stay distinct.
{
 const s=slide('Готовность решения','Работающий прототип для демонстрации',10);
 shape(s,56,244,1168,208,C.white,30);
 text(s,'201',86,263,300,100,78,C.blue);
 text(s,'автоматическая проверка',86,374,470,40,26,C.ink);
 shape(s,619,275,1,142,C.line);
 text(s,'4',664,263,470,100,78,C.blue);
 text(s,'истории по 21 записи',664,374,490,40,26,C.ink);
 text(s,'Следующий шаг',60,493,1150,43,31,C.white,true);
 text(s,'Экспертная оценка описаний и сигналов.\nЗамер времени подготовки врача к приёму.',60,553,1130,86,32,C.light);
 text(s,'Синтетические данные. Клиническая проверка пока не проводилась.',60,673,1150,28,19,C.light);
 notes(s,'201 — сумма 187 серверных и 14 пользовательских автоматических проверок из последнего документированного полного прогона 26.10.2026, не процент качества и не клиническая точность. Проверены также сборка интерфейса, роли, маршруты, сообщения в двух браузерных сессиях, вложения и восстановление после сбоев. Четыре синтетические истории имеют по 21 ежедневной записи. Текущая презентация не содержит результатов испытаний на реальных пациентах, сравнительного измерения экономии времени врача, чувствительности или специфичности сигналов. Предлагаемый следующий этап: согласованная экспертная оценка достаточной выборки и сравнение времени подготовки к приёму в обычном процессе и с системой.',['docs/chat-verification.md:24','docs/demo-scenarios.md','docs/verification.md','var/presentation/benchmark.json']);
}

await fs.mkdir(path.join(BUILD,'renders'),{recursive:true});
for(let i=0;i<p.slides.items.length;i++){
 const png=await p.export({slide:p.slides.items[i],format:'png',scale:1.5});
 await fs.writeFile(path.join(BUILD,'renders',`slide-${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await png.arrayBuffer()));
 console.log(`Rendered ${i+1}`);
}
await (await PresentationFile.exportPptx(p)).save(path.join(BUILD,'candidate.pptx'));
await fs.writeFile(path.join(BUILD,'layout-inspection.ndjson'),(await p.inspect({kind:'slide,textbox,table',maxChars:100000})).ndjson);
console.log('Candidate exported.');
