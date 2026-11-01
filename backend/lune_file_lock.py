"""Small flock compatibility for the optional native JSON stores on Windows."""
import os
if os.name=='nt':
    import msvcrt
    LOCK_EX=2
    LOCK_UN=8
    def flock(fd,operation):
        os.lseek(fd,0,os.SEEK_SET)
        msvcrt.locking(fd,msvcrt.LK_UNLCK if operation==LOCK_UN else msvcrt.LK_LOCK,1)
else:
    from fcntl import flock,LOCK_EX,LOCK_UN
