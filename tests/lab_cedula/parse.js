// Valida 3 líneas con el MISMO lector del navegador (para el servidor de prueba).
const fs=require('fs');const src=fs.readFileSync(require('path').join(__dirname,'..','..','static','js','cedula-readers.js'),'utf8');const a=src.indexOf("'use strict';"),b=src.lastIndexOf('window.CedulaReaders =');
const I=new Function('window','document',src.slice(a,b)+';return {parseMrz,mrzStrong};')({}, {createElement:()=>({getContext:()=>({})})});
const L=JSON.parse(process.argv[2]).map(s=>s.replace(/\s+/g,''));const p=I.parseMrz(L);console.log(JSON.stringify(p&&I.mrzStrong(p)?{valid:true,id:p.cedula,first_name:p.nombre1,last_name:p.apellido1}:{valid:false}));
