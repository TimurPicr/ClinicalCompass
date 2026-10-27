"""Temporary HTTPS address for synthetic testers, with secure same-origin cookies.

The URL is ephemeral. This process owns its tunnel, API, AI worker and scheduler;
Ctrl+C stops them, preserving the database. PostgreSQL/Ollama stay on loopback.
"""
import argparse
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=0,help='Свободный loopback-порт; 0 — выбрать автоматически')
    parser.add_argument('--no-workers',action='store_true',help='Только API/туннель для проверки; не обрабатывать очередь')
    args=parser.parse_args()
    if not shutil.which('cloudflared'):
        parser.error('Установите официальный клиент: brew install cloudflared')
    if not (ROOT/'app/frontend/dist/index.html').is_file():
        parser.error('Сначала выполните npm --prefix app/frontend run build')
    if args.port!=0 and not 1024<=args.port<=65535:
        parser.error('Выберите 0 или порт 1024–65535')
    # Check ownership before creating any public tunnel to an occupied port.
    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1',args.port))
        except OSError:
            parser.error('Порт занят; выберите другой или используйте --port 0')
        port=probe.getsockname()[1]
    children=[]
    def interrupt(*_):
        raise KeyboardInterrupt
    previous_handler=signal.signal(signal.SIGTERM,interrupt)
    temporary=tempfile.TemporaryDirectory(prefix='compass-tunnel-')
    configuration=Path(temporary.name)/'config.yml'
    configuration.write_text('no-autoupdate: true\n')
    try:
        tunnel=subprocess.Popen(['cloudflared','tunnel','--config',str(configuration),'--url',f'http://127.0.0.1:{port}',
                                 '--protocol','http2','--no-autoupdate'],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        children.append(tunnel)
        url=None
        for line in tunnel.stdout:
            match=re.search(r'https://[a-z0-9-]+\.trycloudflare\.com',line)
            if match:
                url=match.group()
                break
            if any(marker in line for marker in ('ERR','error','failed')):
                print(line.rstrip(),flush=True)
        if not url:
            raise RuntimeError('Cloudflare не выдал HTTPS-адрес. Проверьте сеть и повторите.')
        # Drain tunnel logs so its pipe cannot fill. They contain no application data.
        from threading import Thread
        def drain():
            for line in tunnel.stdout:
                if 'ERR' in line:
                    print(line.rstrip(),flush=True)
        Thread(target=drain,daemon=True).start()
        env={**os.environ,'PUBLIC_URL':url,'ALLOWED_ORIGINS':url,'COOKIE_SECURE':'true'}
        commands=[[sys.executable,'-m','uvicorn','app.backend.main:app','--host','127.0.0.1','--port',str(port),'--no-access-log']]
        if not args.no_workers:
            commands.extend([[sys.executable,'-m','app.backend.ai.worker'],[sys.executable,'-m','scripts.scheduler']])
        for command in commands:
            children.append(subprocess.Popen(command,cwd=ROOT,env=env))
        print(f'Синтетическая тестовая среда: {url}',flush=True)
        print('Оставьте этот терминал и MacBook включёнными. Остановка: Ctrl+C.',flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(0.5)
        raise RuntimeError('Один из процессов завершился; остальные остановлены.')
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGTERM,previous_handler)
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        temporary.cleanup()


if __name__=='__main__':
    main()
