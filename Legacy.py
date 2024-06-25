#!/usr/bin/env python3
# https://github.com/rayliu0712/Launch
import asyncio
import hashlib
import os
import os.path as op
import shutil
import subprocess
import time
from adbutils import AdbDevice, ShellReturn, adb
from concurrent.futures import ThreadPoolExecutor
from sys import argv, maxsize
from typing import Callable
from tqdm import tqdm


class Device(AdbDevice):
    class __ShResult:
        def __init__(self, sr: ShellReturn):
            self.succeed = sr.returncode == 0
            self.fail = not self.succeed
            self.output = sr.output

    def __init__(self, serial: str):
        super().__init__(adb, serial)

    def sh(self, cmd: str) -> __ShResult:
        return Device.__ShResult(self.shell2(cmd, rstrip=True))

    def runas(self, cmd: str) -> __ShResult:
        return self.sh(f'run-as rl.launch {cmd}')

    def pwd(self, cmd: str = '') -> __ShResult:
        sr = self.sh(f'cd "{sdcard}" && {cmd} {'' if cmd == '' else ';'}pwd')
        lines = sr.output.splitlines()
        lines[-1] = lines[-1].replace('//', '/')
        sr.output = '\n'.join(lines)
        return sr

    def exists(self, path: str) -> bool:
        return self.sh(f'[[ -e "{path}" ]]').succeed


class U:
    @staticmethod
    def sha256(string: str) -> str:
        return hashlib.sha256(bytes(string, 'utf-8')).hexdigest()

    @staticmethod
    def safe_name(path: str, checker: Callable[[str], bool], return_full: bool) -> str:
        pwe, ext = op.splitext(path)
        n = ''
        for x in range(1, maxsize):
            if checker(f'{pwe}{n}{ext}'):
                n = f' ({x})'
            else:
                if return_full:
                    return f'{pwe}{n}{ext}'
                else:
                    return op.basename(f'{pwe}{n}{ext}')

    @staticmethod
    def local_size(path: str) -> int:
        if not op.exists(path):
            return 0

        if not op.isdir(path):
            return op.getsize(path)

        size = 0
        for r, _, fs in os.walk(path):
            size += sum(op.getsize(op.join(r, f)) for f in fs)
        return size

    @staticmethod
    def remote_size(path: str) -> int:
        try:
            # sh always succeed here
            return int(d.sh("find '%s' -type f -exec du -cb {} + | grep total$ | awk '{print $1}'" % path).output)
        except ValueError:
            return 0

    @staticmethod
    def visual_size(length) -> str:
        i = 0
        while length >= 1024:
            length /= 1024
            i += 1

        if length - int(length) == 0:
            length = int(length)
        else:
            length = round(length, 2)

        return f'{length}{['B', 'KB', 'MB', 'GB'][i]}'


sdcard = ''


def shell_mode(is_push: bool):
    global sdcard
    while True:
        try:
            cmd = input(f'{sdcard} > ')

            if cmd.endswith('\\'):
                print('命令不能以 "\\" 結尾')

            elif cmd.startswith('size '):
                path = d.pwd(f'cd {cmd.lstrip('size ').strip().strip('"').strip("'")}').output
                path += ('/' if path == '/sdcard' else '')
                size = U.remote_size(path)
                print(f'{U.visual_size(size)} ({size}B)')

            elif cmd == 'ok' and is_push:
                hd = U.sha256(f'{sdcard}{time.time()}')
                if d.pwd(f'touch {hd}; rm {hd}').succeed:
                    break
                else:
                    print('只能Push至 "/sdcard/..."')

            elif cmd in ['clear', 'cls']:
                os.system('cls' if os.name == 'nt' else 'clear')

            else:
                out = d.pwd(cmd).output.splitlines()
                sdcard = out.pop()
                for o in out:
                    print(o)

        except KeyboardInterrupt:
            print('KeyboardInterrupt')


async def async_tqdm():
    # Requires global var "total_size: int" "monitor: Callable[[], int]"
    counter = 0
    with tqdm(total=total_size, unit='B', unit_scale=True, unit_divisor=1024) as pbar:
        while counter < total_size:
            n = monitor_fun() - counter
            counter += n
            pbar.update(n)


while True:
    dl = adb.device_list()

    if len(dl) == 1:
        d = Device(dl[0].serial)
        break

    print(f'\n{len(dl)} device(s)')
    for i, it in enumerate(dl):
        print(f'[{i}] {it.prop.model}')

    try:
        d = Device(dl[int(input('> ').strip())].serial)
        break
    except ValueError:
        pass
    except IndexError:
        pass

del argv[0]
if not argv:
    while True:
        sr = d.runas("cat ./files/launch.txt")
        if sr.succeed:
            d.runas('touch ./files/key_a')
            break
        else:
            print('Waiting For Launch \\', end='\r', flush=True)
            time.sleep(0.25)
            print('Waiting For Launch |', end='\r', flush=True)
            time.sleep(0.25)
            print('Waiting For Launch /', end='\r', flush=True)
            time.sleep(0.25)
            print('Waiting For Launch -', end='\r', flush=True)
            time.sleep(0.25)

    src_s = sr.output.splitlines()
    total_size = int(src_s.pop(0))
    dst_s = [op.basename(src) for src in src_s]


    def monitor_fun() -> int:
        return sum(U.local_size(dst) for dst in dst_s)


    def transfer_fun():
        for i, src in enumerate(src_s):
            d.sync.pull(src, U.safe_name(dst_s[i], op.exists, True))


    def completed_fun():
        for dst in dst_s:
            for r, _, fs in os.walk(dst):
                [os.remove(op.join(r, f)) for f in fs if f.startswith('.trashed')]
        d.runas('touch ./files/key_b')

elif argv[-1] == '-':
    shell_mode(False)

else:
    print('選擇Push目的地')
    print('[ Enter ] ./Download')
    print('[   1   ] ./Documents')
    print('[   2   ] ./Pictures')
    print('[   3   ]   AstroDX')
    print('[   4   ]   Custom')

    while True:
        chosen = input('> ').strip()
        try:
            sdcard = {'': '/sdcard/Download',
                      '1': '/sdcard/Documents',
                      '2': '/sdcard/Pictures',
                      '3': '/sdcard/Android/data/com.Reflektone.AstroDX/files/levels',
                      '4': '/sdcard'}[chosen]
            if chosen == '3' and d.pwd().fail:
                sdcard = ''
                print('"./Android/data/com.Reflektone.AstroDX/files/levels" 不存在')
            else:
                break
        except KeyError:
            pass

    if chosen in ['3', '4']:
        print('\n"ok" 選擇當前目錄；可以使用shell命令')
        shell_mode(True)

    total_size = sum(U.local_size(a) for a in argv)
    hd = U.sha256(f'{time.time()}')
    os.mkdir(hd)
    dst_s = []

    for it in argv:
        basename = op.basename(it)
        dst = op.join(hd, U.safe_name(f'{sdcard}/{basename}', d.exists, False))
        dst_s.append(dst)
        shutil.move(it, dst)


    def monitor_fun() -> int:
        return U.remote_size(f'/sdcard/Download/{hd}/')


    def transfer_fun():
        subprocess.check_output(f'adb push {hd} /sdcard/Download/{hd}')


    def completed_fun():
        d.sh(f'cd /sdcard/Download/{hd}; mv * "{sdcard}"; rmdir ../{hd}')
        [shutil.move(dst, src) for dst, src in zip(dst_s, argv)]
        os.rmdir(hd)


async def main():
    loop = asyncio.get_running_loop()

    with ThreadPoolExecutor() as pool:
        print()
        transfer_task = loop.run_in_executor(pool, transfer_fun)
        await asyncio.gather(transfer_task, async_tqdm())
        completed_fun()
        input('\nPress Enter to exit ...')


asyncio.run(main())
