import { useEffect } from 'react';
import { check } from '@tauri-apps/plugin-updater';
import { ask } from '@tauri-apps/plugin-dialog';
import { relaunch } from '@tauri-apps/plugin-process';

export function Updater() {
  useEffect(() => {
    const checkUpdate = async () => {
      try {
        const update = await check();
        if (update) {
          console.info(
            `found update ${update.version} from ${update.date} with notes ${update.body}`
          );
          
          const yes = await ask(
            `Update to ${update.version} is available!\n\nRelease notes: ${update.body}`, 
            {
              title: 'Update Available',
              kind: 'info',
              okLabel: 'Update',
              cancelLabel: 'Cancel'
            }
          );

          if (yes) {
            await update.downloadAndInstall((event) => {
              switch (event.event) {
                case 'Started':
                  console.info(`[Updater] Started downloading ${event.data.contentLength} bytes`);
                  break;
                case 'Progress':
                  console.info(
                    `[Updater] Downloaded ${event.data.chunkLength} bytes`
                  );
                  break;
                case 'Finished':
                  console.info("[Updater] Download finished");
                  break;
              }
            });

            await relaunch();
          }
        }
      } catch (error) {
        console.error('Failed to check for updates', error);
      }
    };

    checkUpdate();
  }, []);

  return null;
}
