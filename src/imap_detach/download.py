import six
from six import print_ as p
from base64 import b64decode
from quopri import decodestring
import re
import os.path
import shutil
from imap_detach.utils import decode, lower_safe
import logging
import subprocess
from threading import Timer
log=logging.getLogger('download')

RE_REPLACE=re.compile(r'[/\\?%*|]')
RE_SKIP=re.compile('["]')
def escape_path(p):
    return RE_REPLACE.sub('_', RE_SKIP.sub('',p))
    
def download(msgid, part_infos, msg_info, filename, command=None, client=None, delete=False, max_time=60,
             message_action=None, message_action_args=None):
        def check_seen():
            res=client.get_flags(msgid)
            flags=res[msgid]
            return b'\\Seen' in flags
        
        seen=check_seen()
        for part_info in part_infos:
            try:
                msg_info.update_part_info(part_info)
                download_part(msgid, part_info, msg_info, filename, command, client, delete, max_time)
            except Exception:
                log.exception('Download failed')
        try:
            if message_action == 'unseen' and not seen:
                log.debug("Marking message id: %s unseen", msgid)
                client.remove_flags(msgid, ['\\Seen'])
            elif message_action == 'delete':
                log.debug("Deleting  message id: %s", msgid)
                client.delete_messages(msgid)
            elif message_action == 'move':
                folder=message_action_args[0]
                log.debug("Moving message id: %s to folder %s", msgid, folder)
                client.copy(msgid, folder)
                client.delete_messages(msgid)
        except Exception:
            log.exception('Message update failed')

def download_part(msgid, part_info, msg_info, filename, command=None, client=None, 
                  delete_file=False, max_time=60):

    part_id=('BODY[%s]'%part_info.section).encode('ascii')
    
    try:
        cmd=CommandRunner(command, filename, msg_info, delete_file, max_time)
    except ValueError as e:
        log.error("Cannot download message: %s",e)
        return
    
    part=client.fetch(msgid, [part_id])
    part=part[msgid][part_id]
    part=decode_part(part, part_info.encoding)
    
    try:
        cmd.run(part)
    except CommandRunner.Error as e:
        pass
    log.debug('Command stdout:\n%s\nCommand stderr:\n%s\n', cmd.stdout, cmd.stderr)
        
        
    
def decode_part(part, encoding):
    if lower_safe(encoding) == 'base64':
        
        missing_padding = 4 - len(part) % 4
        #log.debug ('PAD1: %d %d, %s', len(part), missing_padding, part[-8:]) 
        if missing_padding and missing_padding < 3:
            part += b'='* missing_padding
        elif missing_padding == 3:
            log.error('Invalid base64 padding on part  - can be damaged')
            part=part[:-1]
        #log.debug ('PAD2 %d %d, %s',len(part), missing_padding, part[-8:]) 
        part=b64decode(part)
    elif lower_safe(encoding) == 'quoted-printable':
        part=decodestring(part)  
    return part

class CommandRunner(object):
    class Error(Exception):
        pass
    class Terminated(Error):
        pass
    def __init__(self, command, file_name, context, delete=False, max_time=60):
        if not (command or file_name):
            raise ValueError('File or command must be specified')
        self._file=None
        self._command=None
        v={v: (escape_path(x) if isinstance(x, six.text_type) else str(x)) for v,x in six.iteritems(context) }
        dirname=None
        if file_name:
            fname=file_name.format(**v)
            if not fname:
                raise ValueError('No filename available after vars expansion')
            dirname=os.path.dirname(fname)
            if dirname and not os.path.exists(dirname):
                os.makedirs(dirname)
            if os.path.isdir(fname):
                raise ValueError('Filename %s is directory', 
                          fname)
            self._file=fname
        v['file_name'] = self._file or ''
        v['file_base_name'] = os.path.splitext(os.path.basename(self._file))[0] if self._file else ''
        v['file_dir'] = dirname or ''
        if command:
            cmd = command.format(**v)
            if not cmd:
                raise ValueError('No command available after vars expansion')
            self._command = cmd
            
        self._process=None
        self._stdout=''
        self._stderr=''
        self._killed=False
        self._timer=Timer(max_time, self.terminate)
        self._delete=delete
    
    def terminate(self):
        self._process.kill()
        self._killed=True
        
    def run(self, part):
        if self._file:
            with open(self._file, 'wb') as f:
                f.write(part)
            log.debug("Save file %s", self._file)
        if self._command:
            self._timer.start()
            input_pipe=subprocess.PIPE if not self._file else None
            self._process = subprocess.Popen(self._command, shell=True, 
                            stdin=input_pipe, stderr=subprocess.PIPE, stdout= subprocess.PIPE, 
                            close_fds=True)
            self._stdout, self._stderr =self._process.communicate(None if self._file else part ) 
            self._timer.cancel()
            if self._killed:
                msg= 'Command %s timeouted'% (self._command,)
                log.error(msg)
                raise CommandRunner.Terminated('msg')
            if self._process.returncode != 0:
                msg= 'Command %s failed  with code %d'% (self._command, self._process.returncode)
                log.error(msg)
                raise CommandRunner.Error(msg)
            if self._delete and self._file and os.access(self._file, os.W_OK):
                os.remove(self._file)
            
    @property
    def stdout(self):
        return self._stdout
    
    @property
    def stderr(self):
        return self._stderr
                
            

            
            