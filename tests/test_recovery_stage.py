"""Recovery staging integration tests on disposable files; disk/root tools stubbed."""
import pathlib,tempfile,plistlib,subprocess,os,sys,hashlib,tarfile,json,re,shutil
BASE=pathlib.Path(__file__).resolve().parent.parent/'kit'
results=[]
with tempfile.TemporaryDirectory(prefix='mbp113-recovery-') as td:
 t=pathlib.Path(td).resolve();usb=t/'usb';kit=usb/'MBP113-Repair';kit.mkdir(parents=True);efi=t/'efi';efi.mkdir();vol=t/'volumes';vol.mkdir();system=vol/'MacIntosh';data=vol/'MacIntosh - Data';(data/'Library').mkdir(parents=True);(data/'Users/Shared').mkdir(parents=True)
 root=t/'root';(root/'System/Library').mkdir(parents=True);(root/'System/Library/BaseSystem').touch();mock=t/'mock';mock.mkdir();config=t/'config.json'
 sv=system/'System/Library/CoreServices/SystemVersion.plist';sv.parent.mkdir(parents=True);sv.write_bytes(plistlib.dumps({'ProductVersion':'26.7.1','ProductBuildVersion':'25G241'}))
 sentinel=efi/'EFI-sentinel';sentinel.write_text('existing boot files')
 stub='''#!PYTHON
import sys,os,json,pathlib,plistlib
c=json.load(open(os.environ['TEST_CONFIG']));n=pathlib.Path(sys.argv[0]).name;a=sys.argv[1:];t=pathlib.Path(os.environ['TEST_BASE']);u=t/'usb';e=t/'efi';s=t/'volumes/MacIntosh';d=t/'volumes/MacIntosh - Data'
if n=='sysctl':print(c['model'] if 'hw.model' in a else 'kern.bootargs: -v')
elif n=='diskutil':
 if a[:2]==['info','-plist']:
  q=a[2];o={}
  if q in [str(u),'11111111-2222-4333-8444-555555555555']:o={'DiskUUID':'11111111-2222-4333-8444-555555555555','MountPoint':str(u),'FilesystemType':'hfs','Internal':False,'ParentWholeDisk':'disk-test'}
  elif q=='disk-test-s1':o={'Content':'EFI','MountPoint':str(e),'ParentWholeDisk':'disk-test'}
  elif q in [str(s),str(s)+'2']:o={'Internal':True,'FilesystemType':'apfs','APFSVolumeGroupID':'GROUP-TEST'}
  elif q in [str(d),'disk-data']:o={'Internal':True,'FilesystemType':'apfs','APFSVolumeGroupID':c['data_group'],'MountPoint':str(d)}
  print(plistlib.dumps(o).decode())
 elif a[:3]==['apfs','listVolumeGroups','-plist']:print(plistlib.dumps({'Containers':[{'ContainerReference':'disk-target','VolumeGroups':[{'APFSVolumeGroupUUID':'GROUP-TEST','Volumes':[{'Role':'System','DeviceIdentifier':'disk-system'},{'Role':'Data','DeviceIdentifier':'disk-data'}]}]}]}).decode())
 elif a[:2]==['list','-plist']:print(plistlib.dumps({'AllDisksAndPartitions':[{'Partitions':[{'DeviceIdentifier':'disk-test-s1'}]}]}).decode())
 elif a and a[0]=='list':print('MOCK DISKS')
elif n=='writable':sys.exit(0 if a[0]==str(d) or a[0]==str(e) and c['efi'] or a[0]==str(u) and not c['readonly'] else 1)
elif n=='reboot':(t/'reboot-called').touch()
# codesign, mount, chown and sleep are intentionally inert stubs.
'''.replace('PYTHON',sys.executable)
 for name in ['sysctl','diskutil','writable','reboot','codesign','mount','chown','sleep']:
  p=mock/name;p.write_text(stub);p.chmod(0o755)
 def transform(s):
  s=s.replace('__USB_PARTITION_UUID__','11111111-2222-4333-8444-555555555555')
  for n in ['sysctl','diskutil','reboot','codesign','mount','chown','sleep']:
   for directory in ['/usr/sbin','/usr/bin','/sbin','/bin']:s=s.replace(directory+'/'+n,str(mock/n))
  s=s.replace('"$EUID"','"0"').replace('in /Volumes/*','in '+str(vol)+'/*')
  s=s.replace('[ -e /System/Library/BaseSystem ]','[ -e '+str(root/'System/Library/BaseSystem')+' ]')
  return s
 for name in ['common.sh','startup-repair.sh']:(kit/name).write_text(transform((BASE/name).read_text()))
 with (kit/'common.sh').open('a') as f:f.write('\nwritable() { '+str(mock/'writable')+' "$1"; }\n')
 shutil.copy2(BASE/'recovery-tool',kit/'recovery-tool');shutil.copy2(BASE/'local.mbp113-repair.plist',kit/'local.mbp113-repair.plist');(usb/'repair.sh').write_text(transform((BASE/'repair.sh').read_text()))
 payload=t/'payload';app=payload/'Library/Application Support/Dortania/OpenCore-Patcher.app';(app/'Contents/MacOS').mkdir(parents=True);(app/'Contents/Info.plist').write_bytes(plistlib.dumps({'Github':{'Branch':'refs/tags/3.0.0-rc.3'}}));exe=app/'Contents/MacOS/OpenCore-Patcher';exe.write_text('TEST PLACEHOLDER');exe.chmod(0o755);helper=payload/'Library/PrivilegedHelperTools/com.dortania.opencore-legacy-patcher.privileged-helper';helper.parent.mkdir(parents=True);helper.write_text('TEST PLACEHOLDER');helper.chmod(0o755)
 with tarfile.open(kit/'RC3-runtime.tar.gz','w:gz') as tar:tar.add(payload/'Library',arcname='Library')
 kdk=t/'KDK_26.7.1_25G241.kdk';p=kdk/'System/Library/CoreServices/SystemVersion.plist';p.parent.mkdir(parents=True);p.write_bytes(plistlib.dumps({'ProductBuildVersion':'25G241'}))
 for f in ['System.kext/PlugIns/Libkern.kext/Libkern','apfs.kext/Contents/MacOS/apfs','IOUSBHostFamily.kext/Contents/MacOS/IOUSBHostFamily','AMDRadeonX6000.kext/Contents/MacOS/AMDRadeonX6000']:
  p=kdk/'System/Library/Extensions'/f;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'placeholder')
 with tarfile.open(usb/'KDK-25G241.tar.gz','w:gz') as tar:tar.add(kdk,arcname=kdk.name)
 files=['repair.sh']+[str(p.relative_to(usb)) for p in kit.iterdir() if p.is_file()]+['KDK-25G241.tar.gz']
 (kit/'SHA256SUMS').write_text(''.join(hashlib.sha256((usb/f).read_bytes()).hexdigest()+'  '+f+'\n' for f in files))
 env=dict(os.environ,TEST_CONFIG=str(config),TEST_BASE=str(t))
 staged=data/'Library/Application Support/MBP113-Repair';daemon=data/'Library/LaunchDaemons/local.mbp113-repair.plist'
 def run_case(name,mode,success,**kw):
  c={'model':'MacBookPro11,3','data_group':'GROUP-TEST','readonly':True,'efi':True};c.update(kw);config.write_text(json.dumps(c));(t/'reboot-called').unlink(missing_ok=True)
  r=subprocess.run(['/bin/bash',str(usb/'repair.sh'),mode],env=env,capture_output=True,text=True,timeout=45)
  assert (r.returncode==0)==success,(name,r.returncode,r.stdout,r.stderr)
  assert sentinel.read_text()=='existing boot files'
  results.append({'test':name,'passed':True,'exit':r.returncode});print(name+': passed',flush=True)
 run_case('Recovery entry accepts missing filesystem UUID and logs on EFI','--check',True)
 assert list((efi/'Repair-Logs').glob('*/repair.log'))
 run_case('Full Recovery staging installs runtime, KDK, state and daemon','--repair',True)
 assert daemon.exists() and (staged/'recovery-tool').exists() and (t/'reboot-called').exists()
 assert plistlib.loads((staged/'state.plist').read_bytes())=={'VolumeGroup':'GROUP-TEST','USBPartition':'11111111-2222-4333-8444-555555555555'}
 assert (data/'Library/Developer/KDKs/KDK_26.7.1_25G241.kdk/System/Library/Extensions/System.kext/PlugIns/Libkern.kext/Libkern').is_file()
 snapshot={str(p.relative_to(data)):hashlib.sha256(p.read_bytes()).hexdigest() for p in data.rglob('*') if p.is_file()}
 run_case('Wrong paired Data group stops before repair writes','--repair',False,data_group='WRONG')
 assert snapshot=={str(p.relative_to(data)):hashlib.sha256(p.read_bytes()).hexdigest() for p in data.rglob('*') if p.is_file()}
 run_case('Neither USB volume writable blocks Recovery staging','--repair',False,efi=False)
 assert not (t/'reboot-called').exists()
 with (kit/'common.sh').open('a') as f:f.write('# simulated corruption\n')
 run_case('Changed payload checksum blocks staging','--repair',False)
 assert not (t/'reboot-called').exists()
 (BASE/'recovery-stage-test-results.json').write_text(json.dumps(results,indent=2)+'\n')
