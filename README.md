# Samsung Galaxy A32 4G (SM-A325M): de stock com root pra LineageOS 23.2 (Android 16) — 100% Linux

Guia do processo real, feito em novembro de 2026. CachyOS (Arch), sem Windows, sem Odin.
A parte da **vbmeta com tamanho errado** (que causa `set warranty bit: vbmeta` + bootloop)
não está documentada em lugar nenhum — é o motivo deste guia.

**Requisito do hardware:** SM-A325M com bootloader **A325MUBSBDYC2** (o binário B final
do A325M). Confira em `adb shell getprop ro.boot.bootloader`. O build do LineageOS
só bootaneia nesse binário (A325F usa A325FXXSCDYB2, A325N usa A325NKSS9DYA1).

**Disclaimer:** bootloader destravado = Knox morto para sempre (Samsung Pay/Wallet/Secure
Folder). O processo formata o aparelho. Backup antes, sempre.

## 0. Backup completo via ADB + root (sem TWRP, sem desenhar nada)

Com root Magisk no stock, dá pra salvar tudo por cabo. SELinux bloqueia leitura de
partição mesmo como root — resolva com `su -c "setenforce 0"` antes dos dumps de partição.

Partições críticas (não pule EFS!):

```bash
for p in boot dtbo recovery vbmeta vbmeta_system vbmeta_vendor efs sec_efs \
         nvdata nvram proinfo up_param param lk md1img mmcblk0boot0 mmcblk0boot1; do
  adb exec-out su -c "dd if=/dev/block/by-name/$p bs=4M" > "parts/$p.img" 2>/dev/null
done
```

Dados, por tar stream (o `adb pull /sdcard` via FUSE roda a ~2,5 MB/s; o stream tar
por root roda a ~10 MB/s em arquivos pequenos e 25-35 MB/s em grandes):

```bash
adb exec-out su -c "tar -cf - /data/media/0"  > sdcard_media.tar
adb exec-out su -c "tar -cf - /data/data"     > data_data.tar
adb exec-out su -c "tar -cf - /data/app"      > data_app.tar
adb exec-out su -c "tar -cf - /data/misc 2>/dev/null" > data_misc.tar
```

### Armadilha 1: stderr do celular entra no stdout do adb exec-out

`adb exec-out` **mistura o stderr remoto com o stdout**. O tar imprime
`removing leading '/' from member names` no stderr — os primeiros 39 bytes do seu
tar viram essa frase, e o arquivo inteiro fica deslocado. Um tar de 200 MB morre com
"Este não parece ser um arquivo-tar" e o tamanho não fecha em múltiplo de 512.

**Solução:** suprima stderr DO LADO DO CELULAR, sempre: `tar -cf - /caminho 2>/dev/null`.
Já feitos sem isso? Conserta cortando 39 bytes (`tail -c +40 arquivo.tar > novo.tar`)
e truncando para múltiplo de 512 — o conteúdo sobrevive.

### Armadilha 2: app com pedido de su pendente trava novos pedidos

Um app qualquer (no meu caso o AdAway) com um popup de superusuário pendente na fila
do magiskd faz os seus `su -c` seguintes voltarem como shell (uid 2000) sem erro
aparente. Sintoma: comandos que precisam de root "não fazem nada". Antes de depurar
SELinux, confira `adb shell su -c id`.

## 1. Downloads

- **LineageOS 23.2 (Android 16 QPR2), build UNOFFICIAL por variante:**
  pasta do Drive do dev `_Vigus_` (thread no XDA: "ROM][16][UNOFFICIAL] LineageOS 23.2
  for Galaxy A32 4G") — subpastas `A325F`, `A325M`, `A325N`. Pegue a sua.
- **TWRP 3.7.0_12.1** (testado no A325M):
  `github.com/almondnguyen/twrp_device_samsung_a32/releases` — o `.tar` contém o `recovery.img`.
- **vbmeta disabler:** faça o seu (seção 3) — o "oficial" anexado no XDA tem o mesmo
  problema de tamanho que causa bootloop.

## 2. Flash do recovery via dd (sem download mode)

Com root no stock, o recovery entra por `dd` direto (SELinux permissivo, igual backup):

```bash
adb push recovery.img /data/local/tmp/
adb shell su -c "dd if=/data/local/tmp/recovery.img of=/dev/block/by-name/recovery bs=4M"
# verificação obrigatória:
adb shell su -c "dd if=/dev/block/by-name/recovery bs=32878608 count=1" | md5sum
md5sum recovery.img   # os dois md5 têm que bater
```

## 3. A armadilha central: o tamanho da vbmeta

A partição `vbmeta` do A32 (mt6768/69) tem o device marcado **read-only no kernel**
(`cat /sys/block/mmcblk0/mmcblk0p14/ro` → `1`) — nem como root dá pra escrever nela
(`blockdev --setrw` morre no SELinux). Logo, a vbmeta vai **obrigatoriamente por
download mode** (Heimdall/Odin), que escreve por fora do kernel.

O bootloader (LK) espera **vbmeta de até 65536 bytes**. O dump da partição via `dd`
tem **65614** (a imagem AVB real tem 7616 bytes — o resto é slack). Se você mandar
o arquivo de 65614 pelo Heimdall, ele reclama (`partition is too small for given file`);
com `--skip-size-check` ele escreve, a tela de download mostra o aviso vermelho
`vbmeta binary size (65614) over ... partition size`, e o aparelho pode bootar — mas
nas próximas tentativas entra em **bootloop com `set warranty bit: vbmeta`**, e nem
recovery entra. Truncar para 65536 sem mais nada também quebra (a imagem fica
inválida na estrutura).

### O conserto: vbmeta de exatamente 65536 bytes, estrutura AVB íntegra

Script pronto neste repo: `./fix_vbmeta.py vbmeta_stock.img -o vbmeta_64k_fixed.img --flags 3`

A imagem AVB real tem tamanho = `256 + authentication_data_block_size +
auxiliary_data_block_size` (campos big-endian nos offsets 12 e 20 do header).
Descubra e monte um arquivo com a imagem nos primeiros bytes + zeros até 65536:

```python
import struct
d = open('vbmeta_stock.img','rb').read(300)   # dump da partição
assert d[0:4] == b'AVB0'
auth = struct.unpack('>Q', d[12:20])[0]
aux  = struct.unpack('>Q', d[20:28])[0]
img  = 256 + auth + aux                        # no A32: 7616 bytes
open('vbmeta_64k_fixed.img','wb').write(d[:img])
```

```bash
# flags=3 (desativa hashtree e verification) — byte de flags fica no offset 120:
printf '\x03' | dd of=vbmeta_64k_fixed.img bs=1 seek=120 count=1 conv=notrunc
truncate --size=65536 vbmeta_64k_fixed.img
```

Flash (agora SEM `--skip-size-check` — 65536 passa na checagem, sem aviso vermelho):

```bash
adb reboot download
heimdall flash --vbmeta vbmeta_64k_fixed.img
```

Esse exato arquivo resolveu o bootloop e bootou o sistema de primeira. Se um dia
quiser voltar pro stock íntegro, mesma receita com flags=0x00 (`vbmeta_64k_stock.img`).

## 4. Instalação do LineageOS

Dentro do TWRP (Vol+ + Power; o adb aparece como modo `recovery`):

```bash
adb shell twrp format data          # apaga tudo, remove FBE do stock
adb reboot recovery                 # remonta o /data limpo
adb push lineage-23.2-20261009-UNOFFICIAL-a32.zip /sdcard/
adb push magisk_patched_boot.img /sdcard/
adb shell twrp install /sdcard/lineage-23.2-20261009-UNOFFICIAL-a32.zip
# root: o boot.img do LOS patchado com Magisk, por dd:
adb shell "dd if=/sdcard/magisk_patched_boot.img of=/dev/block/by-name/boot bs=4M"
adb shell twrp reboot system
```

Primeiro boot do LOS demora ~1-2 min. `getprop ro.build.version.release` → `16`.

## 5. Patch do boot com Magisk via CLI (sem tocar no app)

O app Magisk instalado no stock tem tudo em `/data/adb/magisk/` — o patch é o
`boot_patch.sh` que o app roda por baixo:

```bash
adb push boot_los.img /sdcard/Download/
adb shell su -c "cd /data/local/tmp && sh /data/adb/magisk/boot_patch.sh /sdcard/Download/boot_los.img"
adb pull /data/local/tmp/new-boot.img
```

Na LOS/One UI com SELinux re-forçando, o acesso a `/data/adb` pode falhar mesmo como
root (`Permission denied` em execução). Plano B: `adb pull` do APK do Magisk → extrair
`assets/boot_patch.sh`, `assets/util_functions.sh` e os `lib/arm64-v8a/lib*.so`
(renomear: `libmagisk.so`→`magisk`, `libmagiskboot.so`→`magiskboot`,
`libmagiskinit.so`→`magiskinit`, `libinit-ld.so`→`init-ld`) → push para
`/data/local/tmp/magiskbin/` → rodar de lá. Importante: extraia o config da
instalação ATUAL (`magiskboot cpio ramdisk.cpio "extract .backup/.magisk config"`
no boot em uso) para reutilizar `PREINITDEVICE` (no A32: `cache`) e as flags
`KEEPVERITY/KEEPFORCEENCRYPT` — sem o PREINITDEVICE o Magisk pode não achar o
storage pós-flash.

No LOS sem GApps: instale o APK do Magisk, e se o card mostrar estado incompleto,
o ciclo "abrir app → deixa ele reiniciar" conclui a configuração do preinit.

## 6. Problemas conhecidos e resoluções

- **Heimdall reinicia de volta pro modo download** após o flash (flag sticky pós-sessão
  nesse LK). `heimdall close-pc-screen` não resolve nesses aparelhos. Saída: `Vol− + Power`
  ~15-20 s até desligar de verdade, **desconectar o cabo**, ligar só com Power, e só
  reconectar depois do sistema subir.
- **`heimdall print-pit` derruba a conexão** no modo download do MTK: rode antes uma vez
  só para consultar nomes de partição e refaça o ciclo de download mode para o flash.
- **`set warranty bit: vbmeta` + bootloop** = vbmeta estruturalmente inválida ou maior
  que 65536 na flash. Conserto na seção 3. Com a vbmeta certa, o aviso vermelho some da
  tela de download e o boot volta.
- **vbmeta read-only no kernel:** `dd` e `blockdev --setrw` falham mesmo como root no
  sistema — não perca tempo; o caminho é download mode.
- **SELinux volta pra Enforcing sozinho** no One UI: algo re-força o `enforce`. Combine
  `setenforce 0` e a operação sensível no MESMO comando `su -c`.
- **`pkill -f` mata o próprio comando** se o padrão aparece na linha de comando atual
  (inclusive dentro de heredoc). Use padrão com colchete: `pgrep -f 'backup_p[a]r'`.
- **TWRP 3.7.0_12.1** no A325M: touch funciona, `twrp format data` funciona via CLI,
  flash de zip no super funciona.

### Armadilha 3: Android 16 protege `/data/data` contra o próprio root

No LOS 23.2 (Android 16), o kernel nega a root **criar/chownar** qualquer coisa dentro
de `/data/data/<pkg>` (`mkdir`, `chown`, `chmod` → `Operation not permitted`), mesmo
com SELinux Permissive — é hardening de app-data novo, não SELinux. `unlink` (rm)
continua liberado. Restaurar dados de um app:

```bash
adb install app.apk                        # cria o dir com o uid novo (anote: stat -c %u)
adb shell su -c "rm -rf /data/data/<pkg>/* /data/data/<pkg>/.[!.]*"
adb shell su <uid> -c 'cp -R /data/local/tmp/restauracao/. /data/data/<pkg>/'  # copia COMO o uid do app
adb shell su <uid> -c 'chmod -R go-rwx /data/data/<pkg>'
adb shell su -c "restorecon -R /data/data/<pkg>"
```

Copiar como o uid do app faz os arquivos nascerem com o dono certo — nenhum `chown`
necessário (seria negado). `pm uninstall -k` + reinstalar reusa o mesmo uid, e o
dono dos arquivos no tar original fica irrelevante. Testado restaurando o WhatsApp
completo (key + msgstore.db de 140 MB) — conversas intactas.

**Limite do método:** apps que lacram os dados com `AndroidKeyStore` (Proton
Authenticator, alguns bancos) NÃO sobrevivem ao `format data`, mesmo com a cópia
perfeita de `/data/data` — as chaves de hardware são apagadas no format e o blob
criptografado vira lixo (crash em `EncryptionContextProvider.getKey`). Authenticator
com conta Proton (sync E2E) ou export local agendado; seeds TOTP sempre com backup
codes guardados fora do aparelho.

## 7. Estado final e restauração seletiva

Restore de mídia por `adb push` de pastas (34 MB/s). Dados de apps: pelo método da
Armadilha 3 (copiar como o uid do app), um app por vez, nunca o `/data/data` inteiro.

Créditos: [_Vigus_](https://github.com/samsung-mt6768-aosp) (build LOS 23.2),
AndroidHQ254 (trees), Prove N./almondnguyen (TWRP), ianmacd (multidisabler),
Long266, Melky777 (testes A325M), e a comunidade do XDA do A32 4G.
