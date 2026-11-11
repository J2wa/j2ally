#define UNICODE
#define _UNICODE
#include <windows.h>
#include <shlobj.h>
#include <stdio.h>
#include <stdint.h>
#include <wchar.h>
#ifndef ALLY_BUILD
#define ALLY_BUILD L"2.1.0"
#endif
static int error(const wchar_t *s) { MessageBoxW(NULL,s,L"ALLY — ACES INTELLIGENCE",MB_OK|MB_ICONERROR); return 1; }
static BOOL exists(const wchar_t *p) { return GetFileAttributesW(p)!=INVALID_FILE_ATTRIBUTES; }
int WINAPI wWinMain(HINSTANCE instance,HINSTANCE prev,LPWSTR args,int show) {
    wchar_t self[32768],local[MAX_PATH],root[32768],zip[32768],marker[32768],python[32768],mainfile[32768],cmd[32768],ps[MAX_PATH];
    if (!GetModuleFileNameW(NULL,self,32768) || SHGetFolderPathW(NULL,CSIDL_LOCAL_APPDATA,NULL,SHGFP_TYPE_CURRENT,local)!=S_OK) return error(L"Cannot locate ALLY or your local application folder.");
    swprintf(root,32768,L"%ls\\AcesIntelligence\\ALLY\\%ls",local,ALLY_BUILD);
    swprintf(zip,32768,L"%ls\\bundle.zip",root); swprintf(marker,32768,L"%ls\\ready",root);
    swprintf(python,32768,L"%ls\\runtime\\pythonw.exe",root);swprintf(mainfile,32768,L"%ls\\app\\main.py",root);
    // Serialize first-run extraction when the executable is double-clicked twice.
    HANDLE mutex=CreateMutexW(NULL,FALSE,L"Local\\ALLY-Extract-" ALLY_BUILD);
    if (!mutex) return error(L"Cannot initialize ALLY.");
    DWORD lock=WaitForSingleObject(mutex,180000);
    if (lock!=WAIT_OBJECT_0 && lock!=WAIT_ABANDONED) {CloseHandle(mutex);return error(L"Another ALLY startup is still preparing. Try again shortly.");}
    if (!exists(marker)||!exists(python)||!exists(mainfile)) {
        int result=SHCreateDirectoryExW(NULL,root,NULL);
        if(result!=ERROR_SUCCESS&&result!=ERROR_ALREADY_EXISTS&&result!=ERROR_FILE_EXISTS) {ReleaseMutex(mutex);CloseHandle(mutex);return error(L"Cannot create ALLY's application folder.");}
        HANDLE src=CreateFileW(self,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,0,NULL);
        LARGE_INTEGER size,seek; DWORD read; unsigned char footer[16]; uint64_t bytes=0;
        if(src==INVALID_HANDLE_VALUE||!GetFileSizeEx(src,&size)||size.QuadPart<16) return error(L"The ALLY download is incomplete. Download it again.");
        seek.QuadPart=-16;SetFilePointerEx(src,seek,NULL,FILE_END);
        if(!ReadFile(src,footer,16,&read,NULL)||read!=16||memcmp(footer,"ALLYZIP1",8)!=0) return error(L"ALLY's bundled runtime is missing. Download the complete executable again.");
        memcpy(&bytes,footer+8,8);
        if(bytes==0||bytes>(uint64_t)size.QuadPart-16) return error(L"ALLY's bundled runtime is damaged.");
        seek.QuadPart=size.QuadPart-16-bytes;SetFilePointerEx(src,seek,NULL,FILE_BEGIN);
        HANDLE dst=CreateFileW(zip,GENERIC_WRITE,0,NULL,CREATE_ALWAYS,0,NULL);
        if(dst==INVALID_HANDLE_VALUE)return error(L"Cannot unpack ALLY. Check available disk space and folder permissions.");
        unsigned char buffer[65536];BOOL ok=TRUE;
        while(bytes){DWORD wanted=bytes>sizeof(buffer)?sizeof(buffer):(DWORD)bytes,written;
            if(!ReadFile(src,buffer,wanted,&read,NULL)||read!=wanted||!WriteFile(dst,buffer,read,&written,NULL)||written!=read){ok=FALSE;break;}bytes-=read;}
        CloseHandle(src);CloseHandle(dst);
        if(!ok)return error(L"Could not write the bundled runtime. Check disk space and download ALLY again.");
        SetEnvironmentVariableW(L"ALLY_EXTRACT_ZIP",zip);SetEnvironmentVariableW(L"ALLY_EXTRACT_DEST",root);
        GetSystemDirectoryW(ps,MAX_PATH);wcscat(ps,L"\\WindowsPowerShell\\v1.0\\powershell.exe");
        swprintf(cmd,32768,L"\"%ls\" -NoLogo -NoProfile -NonInteractive -Command \"& { $ErrorActionPreference='Stop'; Expand-Archive -LiteralPath $env:ALLY_EXTRACT_ZIP -DestinationPath $env:ALLY_EXTRACT_DEST -Force; if (!(Test-Path -LiteralPath (Join-Path $env:ALLY_EXTRACT_DEST 'runtime\\pythonw.exe'))) { throw 'Runtime missing' }; Set-Content -LiteralPath (Join-Path $env:ALLY_EXTRACT_DEST 'ready') -Value 'ALLY' }\"",ps);
        SetProcessDPIAware();
        HWND splash=CreateWindowExW(WS_EX_TOPMOST,L"STATIC",L"ALLY — Preparing your interview assistant",WS_OVERLAPPED|WS_CAPTION|WS_VISIBLE,400,300,520,145,NULL,NULL,instance,NULL);
        CreateWindowW(L"STATIC",L"Setting up the bundled runtime for first use.\nThis may take a minute. No Python installation is needed.",WS_CHILD|WS_VISIBLE,20,25,480,70,splash,NULL,instance,NULL);
        UpdateWindow(splash);
        STARTUPINFOW si={sizeof(si)}; PROCESS_INFORMATION pi={0};
        if(!CreateProcessW(ps,cmd,NULL,NULL,FALSE,CREATE_NO_WINDOW,NULL,root,&si,&pi)){DestroyWindow(splash);return error(L"Windows PowerShell could not start. ALLY requires the built-in Expand-Archive command for first-run setup.");}
        DWORD wait;MSG msg;
        do{wait=WaitForSingleObject(pi.hProcess,50);while(PeekMessageW(&msg,NULL,0,0,PM_REMOVE)){TranslateMessage(&msg);DispatchMessageW(&msg);}}while(wait==WAIT_TIMEOUT);
        DWORD code=1;GetExitCodeProcess(pi.hProcess,&code);CloseHandle(pi.hProcess);CloseHandle(pi.hThread);DestroyWindow(splash);
        SetEnvironmentVariableW(L"ALLY_EXTRACT_ZIP",NULL);SetEnvironmentVariableW(L"ALLY_EXTRACT_DEST",NULL);
        DeleteFileW(zip);
        if(code!=0||!exists(python)||!exists(mainfile)){DeleteFileW(marker);return error(L"ALLY could not finish setup. Check disk space and that Windows PowerShell is permitted, then try again.");}
    }
    ReleaseMutex(mutex);CloseHandle(mutex);
    swprintf(cmd,32768,L"\"%ls\" \"%ls\"",python,mainfile);
    STARTUPINFOW si={sizeof(si)};PROCESS_INFORMATION pi={0};
    if(!CreateProcessW(python,cmd,NULL,NULL,FALSE,0,NULL,root,&si,&pi))return error(L"ALLY could not launch. Delete its runtime folder under LocalAppData\\AcesIntelligence\\ALLY and try again.");
    CloseHandle(pi.hThread);CloseHandle(pi.hProcess);return 0;
}
