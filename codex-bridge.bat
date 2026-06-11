/* 2>"%TEMP%\codex-bridge-start.log"
@echo off
title Codex Bridge
chcp 65001
node -v
if errorlevel 1 (
  echo [ERROR] Node.js is not installed or not in PATH.
  echo         Install Node.js from https://nodejs.org and run this file again.
  pause
  exit /b 1
)
echo Starting Codex bridge from this single file... close this window to stop it.
node "%~f0"
pause
exit /b
*/
/*
 * Codex CLI 연결 프로그램 (강사 전용) — 단일 파일 버전
 * ----------------------------------------------------
 * 이 파일 하나가 윈도우 실행파일(bat)이자 프로그램 본체(JS)입니다.
 * 더블클릭하면 스스로를 Node.js로 실행합니다. 다른 파일이 필요 없습니다.
 *
 * 사용법:
 *   1. Codex CLI가 설치되어 있고 로그인된 상태여야 합니다. (터미널에서 `codex` 실행 확인)
 *   2. 이 파일을 더블클릭 (맥/리눅스는: node codex-bridge.bat)
 *   3. 편집기를 열면 AI 선택에 "Codex CLI (내 컴퓨터)" 옵션이 자동으로 나타납니다.
 *
 * 이 프로그램이 꺼져 있으면 편집기에 Codex 옵션이 아예 보이지 않으므로,
 * 수강생에게는 HTML 파일만 전달하면 됩니다.
 */
'use strict';
const http = require('http');
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const PORT = 8787;
const CODEX_TIMEOUT_MS = 5 * 60 * 1000;

function cors(res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  res.setHeader('Access-Control-Allow-Methods', 'GET,POST,OPTIONS');
}

/*
 * codex exec 실행. 인자 토큰에 공백이 없도록 작업 폴더(cwd) 기준 상대 경로만 쓰고,
 * 프롬프트(한글/따옴표 포함)는 셸 인용 문제가 없도록 stdin으로 전달한다.
 */
function runCodex(args, cwd, promptText) {
  return new Promise((resolve) => {
    const child = spawn('codex', args, {
      cwd,
      shell: process.platform === 'win32', // 윈도우에서 codex.cmd를 PATH로 찾기 위함
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    let stdout = '', stderr = '', done = false;
    const finish = (result) => { if (!done) { done = true; resolve(result); } };
    const timer = setTimeout(() => {
      try { child.kill(); } catch (e) {}
      finish({ code: -1, stdout, stderr: stderr + '\n(시간 초과)' });
    }, CODEX_TIMEOUT_MS);
    child.stdout.on('data', (d) => stdout += d);
    child.stderr.on('data', (d) => stderr += d);
    child.on('error', (err) => {
      clearTimeout(timer);
      const msg = err.code === 'ENOENT'
        ? 'Codex CLI를 찾을 수 없습니다. 터미널에서 `codex` 명령이 실행되는지 확인해 주세요. (npm install -g @openai/codex)'
        : String(err);
      finish({ code: -1, stdout, stderr: msg });
    });
    child.on('close', (code) => { clearTimeout(timer); finish({ code, stdout, stderr }); });
    child.stdin.on('error', () => {});
    child.stdin.write(promptText);
    child.stdin.end();
  });
}

async function translate(data) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'codex-bridge-'));
  try {
    const args = ['exec', '--skip-git-repo-check'];
    (data.images || []).forEach((b64, i) => {
      const name = 'img' + i + '.jpg';
      fs.writeFileSync(path.join(dir, name), Buffer.from(b64, 'base64'));
      args.push('--image', name);
    });
    const outName = 'last_message.txt';
    const prompt = String(data.prompt || '');

    // 1차: 최종 답변만 파일로 받는 옵션 사용
    let r = await runCodex([...args, '--output-last-message', outName], dir, prompt);
    let text = '';
    const outPath = path.join(dir, outName);
    if (fs.existsSync(outPath)) text = fs.readFileSync(outPath, 'utf8').trim();

    // 구버전 Codex가 해당 옵션을 모르면 옵션 없이 재시도하고 stdout에서 추출
    if (!text && r.code !== 0 && /output-last-message|unexpected argument|unrecognized/i.test(r.stderr)) {
      r = await runCodex(args, dir, prompt);
    }
    if (!text) text = (r.stdout || '').trim();
    if (!text && r.code !== 0) {
      return { error: (r.stderr || '알 수 없는 오류').slice(0, 2000) };
    }
    return { text };
  } finally {
    try { fs.rmSync(dir, { recursive: true, force: true }); } catch (e) {}
  }
}

http.createServer((req, res) => {
  cors(res);
  if (req.method === 'OPTIONS') { res.writeHead(204); return res.end(); }
  if (req.url === '/ping') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    return res.end('{"ok":true,"service":"codex-bridge"}');
  }
  if (req.method === 'POST' && req.url === '/translate') {
    let body = '';
    req.on('data', (c) => {
      body += c;
      if (body.length > 100 * 1024 * 1024) req.destroy();
    });
    req.on('end', async () => {
      let data;
      try { data = JSON.parse(body); }
      catch (e) {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        return res.end('{"error":"잘못된 요청"}');
      }
      console.log(`[codex-bridge] 번역 요청: 이미지 ${(data.images || []).length}장 → Codex 실행 중...`);
      const result = await translate(data);
      if (result.error) console.log('[codex-bridge] 오류:', result.error.split('\n')[0]);
      else console.log('[codex-bridge] 완료');
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(result));
    });
    return;
  }
  res.writeHead(404); res.end();
}).listen(PORT, '127.0.0.1', () => {
  console.log('======================================================');
  console.log(' Codex CLI 연결 프로그램이 켜졌습니다. (강사 전용)');
  console.log(` 주소: http://127.0.0.1:${PORT}`);
  console.log(' 이제 영상 편집기를 열면 AI 선택에');
  console.log(' "Codex CLI (내 컴퓨터)" 옵션이 나타납니다.');
  console.log(' 이 창을 닫으면 Codex 옵션도 함께 사라집니다.');
  console.log('======================================================');
});
