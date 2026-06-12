#!/usr/bin/env node
/*
 * Codex CLI 연결 프로그램 (강사 전용)
 * ------------------------------------
 * 영상 편집기(video_editor.html)가 내 컴퓨터에 설치된 Codex CLI로
 * 자막 번역을 요청할 수 있게 해주는 작은 로컬 서버입니다.
 *
 * 사용법:
 *   1. Codex CLI가 설치되어 있고 로그인된 상태여야 합니다. (터미널에서 `codex` 실행 확인)
 *   2. 이 파일을 실행: node codex-bridge.js   (윈도우는 codex-bridge.bat 더블클릭)
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

const PORT = 8788;   // 8787은 카페아사다 로컬 서버가 사용 중이라 충돌 방지
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
      let msg = r.stderr || '알 수 없는 오류';
      if (/not recognized|찾을 수 없|ENOENT/i.test(msg)) {
        msg = 'Codex CLI가 설치되어 있지 않습니다.\n'
            + '명령 프롬프트에서 npm install -g @openai/codex 실행 → codex 명령으로 로그인 →\n'
            + '이 연결 프로그램을 껐다 다시 켠 뒤 시도해 주세요.';
      }
      return { error: msg.slice(0, 2000) };
    }
    return { text };
  } finally {
    try { fs.rmSync(dir, { recursive: true, force: true }); } catch (e) {}
  }
}

const server = http.createServer((req, res) => {
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
});

/* 8787 포트가 이미 사용 중일 때: 에러로 죽지 않고 원인을 안내한다 */
server.on('error', (err) => {
  if (err.code !== 'EADDRINUSE') { console.error(err); process.exit(1); }
  http.get({ host: '127.0.0.1', port: PORT, path: '/ping', timeout: 3000 }, (r) => {
    let b = '';
    r.on('data', (c) => b += c);
    r.on('end', () => {
      if (b.includes('codex-bridge')) {
        console.log('');
        console.log(' 이미 Codex 연결 프로그램이 켜져 있습니다. 새로 켤 필요가 없습니다.');
        console.log(' (이 창은 닫아도 됩니다 — 기존에 켜진 창만 있으면 편집기가 정상 동작합니다)');
      } else {
        console.log('');
        console.log(` [ERROR] 다른 프로그램이 ${PORT} 포트를 사용 중입니다.`);
        console.log(' 명령 프롬프트에서 아래를 실행해 점유 프로세스를 확인/종료한 뒤 다시 실행하세요:');
        console.log(`   netstat -ano | findstr :${PORT}     (맨 끝 숫자가 PID)`);
        console.log('   taskkill /PID 그숫자 /F');
      }
      process.exit(0);
    });
  }).on('error', () => {
    console.log('');
    console.log(` [ERROR] ${PORT} 포트가 이미 사용 중인데 응답이 없습니다.`);
    console.log(' 이전에 실행한 창(또는 남은 node 프로세스)이 있는지 확인하세요:');
    console.log(`   netstat -ano | findstr :${PORT}     (맨 끝 숫자가 PID)`);
    console.log('   taskkill /PID 그숫자 /F');
    process.exit(1);
  });
});

server.listen(PORT, '127.0.0.1', () => {
  console.log('======================================================');
  console.log(' Codex CLI 연결 프로그램이 켜졌습니다. (강사 전용)');
  console.log(` 주소: http://127.0.0.1:${PORT}`);
  console.log(' 이제 영상 편집기를 열면 AI 선택에');
  console.log(' "Codex CLI (내 컴퓨터)" 옵션이 나타납니다.');
  console.log(' 이 창을 닫으면 Codex 옵션도 함께 사라집니다.');
  console.log('======================================================');
  // 시작하면서 Codex CLI 설치 여부를 미리 확인해 준다
  const probe = spawn('codex', ['--version'], { shell: process.platform === 'win32' });
  let probeOut = '';
  probe.stdout.on('data', (d) => probeOut += d);
  probe.on('error', () => {});
  probe.on('close', (code) => {
    if (code === 0) {
      console.log(' Codex CLI 확인됨: ' + probeOut.trim());
    } else {
      console.log('');
      console.log(' [주의] Codex CLI를 찾을 수 없습니다 — 이대로는 번역이 실패합니다.');
      console.log(' 명령 프롬프트에서 아래를 실행한 뒤, 이 창을 껐다 다시 켜세요:');
      console.log('   npm install -g @openai/codex');
      console.log('   codex          (ChatGPT 계정으로 로그인)');
    }
  });
});
