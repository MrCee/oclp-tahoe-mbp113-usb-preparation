"""Sandboxed integration checks: no commands can reach real disks or root patcher."""
import pathlib, tempfile, plistlib, subprocess, os, hashlib, shutil, json, re, sys
BASE=pathlib.Path(__file__).resolve().parent.parent/'kit'
results=[]
with tempfile.TemporaryDirectory(prefix='mbp113-tests-') as td:
 t=pathlib.Path(td); root=t/'root'; usb=t/'usb'; kit=usb/'MBP113-Repair'; mock=t/'mock'; mock.mkdir();kit.mkdir(parents=True)
 target=root/'Library/Application Support/MBP113-Repair';target.mkdir(parents=True)
 model='MacBookPro11,3';build='25G241';group='GROUP-TEST';usb_uuid='AAAAAAAA-BBBB-4CCC-8DDD-EEEEEEEEEEEE'; partition_uuid='11111111-2222-4333-8444-555555555555'; efi=t/'efi'; efi.mkdir()
 config=t/'mock.json'
 def write_config(**kw):
  d=dict(model=model,build=build,group=group,usb=True,cli='complete',partition='11111111-2222-4333-8444-555555555555',readonly=False,efi=True,filesystem='hfs',omit_volume_uuid=False);d.update(kw);config.write_text(json.dumps(d))
 stub='''#!PYTHON
import sys,json,pathlib,plistlib,os
c=json.load(open(os.environ['TEST_CONFIG']));name=pathlib.Path(sys.argv[0]).name;a=sys.argv[1:];r=pathlib.Path(os.environ['TEST_ROOT']);u=pathlib.Path(os.environ['TEST_USB']);efi=pathlib.Path(os.environ['TEST_EFI'])
if name=='sysctl':
 print(c['model'] if 'hw.model' in a else 'kern.bootargs: -v')
elif name=='diskutil':
 if a[:2]==['info','-plist']:
  q=a[2];d={}
  if q==str(u) or q=='11111111-2222-4333-8444-555555555555':
   if c['usb']:
    d={'DiskUUID':c['partition'],'MountPoint':str(u),'Internal':False,'FilesystemType':c['filesystem'],'ParentWholeDisk':'disk-test'}
    if not c['omit_volume_uuid']:d['VolumeUUID']='AAAAAAAA-BBBB-4CCC-8DDD-EEEEEEEEEEEE'
  elif q=='disk-test-s1':d={'Content':'EFI','ParentWholeDisk':'disk-test','MountPoint':str(efi)}
  elif q=='/':d={'APFSVolumeGroupID':c['group']}
  print(plistlib.dumps(d).decode())
 elif a[:3]==['apfs','listVolumeGroups','-plist']:print(plistlib.dumps({'Containers':[]}).decode())
 elif a[:2]==['list','-plist']:print(plistlib.dumps({'AllDisksAndPartitions':[{'Partitions':[{'DeviceIdentifier':'disk-test-s1'}]}]}).decode())
 elif a and a[0]=='list':print('TEST DISKS ONLY')
elif name=='caffeinate':
 (r/'cli-called').write_text('called')
 print('- Installing Patchset: Intel Haswell')
 if c['cli']=='complete':print('- Installing Patchset: Nvidia Kepler');print('- Patching complete')
 elif c['cli']=='failed':print('Failed to mount root volume');sys.exit(1)
elif name=='writable':
 sys.exit(0 if (a[0]==str(u) and not c['readonly']) or (a[0]==str(efi) and c['efi']) else 1)
elif name=='reboot':(r/'reboot-called').write_text('called')
else:print('mock '+name)
'''
 stub=stub.replace('PYTHON',sys.executable)
 for n in ['sysctl','diskutil','caffeinate','reboot','sleep','codesign','csrutil','ioreg','pmset','mount','writable']:
  p=mock/n;p.write_text(stub);p.chmod(0o755)
 def transform(s):
  # Absolute references to tools that could affect the host are replaced in test copies.
  for n in ['sysctl','diskutil','caffeinate','reboot','sleep','codesign','csrutil','ioreg','pmset','mount','writable']:
   for directory in ['/usr/sbin','/usr/bin','/sbin','/bin']:
    s=s.replace(directory+'/'+n,str(mock/n))
  s=s.replace('"$EUID"','"0"')
  s=re.sub(r'(?<![\w$}])(?:/System/Library|/System/Volumes|/Library/|/Users/Shared)',lambda m: str(root)+m.group(0),s)
  return s
 common=transform((BASE/'common.sh').read_text().replace('__USB_PARTITION_UUID__', '11111111-2222-4333-8444-555555555555')).replace('in /Volumes/*', 'in '+str(t/'volumes')+'/*')
 # APP and HELPER are relative paths prefixed with / when used in startup.
 common=common.replace("APP='Library/", "APP='"+str(root).lstrip('/')+"/Library/")
 common=common.replace("HELPER='Library/", "HELPER='"+str(root).lstrip('/')+"/Library/")
 common += '\nwritable() { '+str(mock/'writable')+' \"$1\"; }\n'
 (target/'common.sh').write_text(common)
 shutil.copy2(BASE/'recovery-tool',target/'recovery-tool')
 startup=t/'startup.sh';startup.write_text(transform((BASE/'startup-repair.sh').read_text()).replace('[ "$i" -lt 36 ]', '[ "$i" -lt 2 ]'))
 version=root/'System/Library/CoreServices/SystemVersion.plist';version.parent.mkdir(parents=True)
 version.write_bytes(plistlib.dumps({'ProductBuildVersion':build}))
 (target/'state.plist').write_bytes(plistlib.dumps({'VolumeGroup':group,'USBPartition':partition_uuid}))
 app=root/'Library/Application Support/Dortania/OpenCore-Patcher.app';(app/'Contents/MacOS').mkdir(parents=True)
 (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'Github':{'Branch':'refs/tags/3.0.0-rc.3'}}))
 helper=root/'Library/PrivilegedHelperTools/com.dortania.opencore-legacy-patcher.privileged-helper';helper.parent.mkdir();helper.touch();helper.chmod(0o4755)
 kdk=root/'Library/Developer/KDKs/KDK_26.7.1_25G241.kdk';kp=kdk/'System/Library/CoreServices/SystemVersion.plist';kp.parent.mkdir(parents=True);kp.write_bytes(plistlib.dumps({'ProductBuildVersion':build}))
 for f in ['System.kext/PlugIns/Libkern.kext/Libkern','apfs.kext/Contents/MacOS/apfs','IOUSBHostFamily.kext/Contents/MacOS/IOUSBHostFamily','AMDRadeonX6000.kext/Contents/MacOS/AMDRadeonX6000']:
  p=kdk/'System/Library/Extensions'/f;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'test')
 daemon=root/'Library/LaunchDaemons/local.mbp113-repair.plist';daemon.parent.mkdir()
 env=dict(os.environ,TEST_CONFIG=str(config),TEST_ROOT=str(root),TEST_USB=str(usb),TEST_EFI=str(efi))
 def case(name,expected_cli,expected_done,expected_reboot,**kw):
  for f in ['attempted','completed','.running']:
   p=target/f
   if p.is_dir():p.rmdir()
   elif p.exists():p.unlink()
  for f in ['cli-called','reboot-called']:
   (root/f).unlink(missing_ok=True)
  daemon.write_text('test daemon')
  prior=kw.pop('prior',False)
  if prior:(target/'attempted').write_text('previous attempt')
  write_config(**kw)
  p=subprocess.run(['/bin/bash',str(startup)],env=env,capture_output=True,text=True,timeout=30)
  actual=((root/'cli-called').exists(),(target/'completed').exists(),(root/'reboot-called').exists())
  assert actual==(expected_cli,expected_done,expected_reboot),(name,p.returncode,actual,p.stdout,p.stderr,[(str(f),f.read_text()) for f in (target/'logs').glob('*/startup.log')])
  if expected_done:assert not daemon.exists()
  else:assert daemon.exists()
  results.append({'test':name,'passed':True,'exit':p.returncode})
 case('full graphics completion reboots once',True,True,True)
 case('zero exit with incomplete graphics does not reboot',True,False,False,cli='incomplete')
 case('patcher failure never reboots',True,False,False,cli='failed')
 case('prior attempt blocks automatic retry',False,False,False,prior=True)
 case('wrong model blocks patching',False,False,False,model='iMac15,1')
 case('wrong booted volume group blocks patching',False,False,False,group='WRONG')
 case('absent USB blocks patching',False,False,False,usb=False)
 # Wrong build is read from booted system plist, not the diskutil stub.
 version.write_bytes(plistlib.dumps({'ProductBuildVersion':'WRONG'}))
 case('wrong build blocks patching',False,False,False)
 version.write_bytes(plistlib.dumps({'ProductBuildVersion':build}))
 case('Recovery missing filesystem UUID is accepted',True,True,True,omit_volume_uuid=True)
 case('read-only installer logs to same USB EFI',True,True,True,readonly=True,omit_volume_uuid=True)
 assert list((efi/'Repair-Logs').glob('*/oclp-cli.log'))
 case('neither USB volume writable blocks patching',False,False,False,readonly=True,efi=False)
 case('wrong GPT partition blocks patching',False,False,False,partition='WRONG')
 case('wrong filesystem blocks patching',False,False,False,filesystem='apfs')
 (BASE/'test-results.json').write_text(json.dumps(results,indent=2)+'\n')
 print(json.dumps(results,indent=2))
