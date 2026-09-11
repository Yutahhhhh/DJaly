import { useRef, useState } from 'react';
import { DJ_NAME_MAX_LENGTH, limitDjName, safeAvatarDataUrl, stableThemeColor } from '@/services/junction/roster-model';

const AVATAR_MAX_CHARS = 4_096;
const SOURCE_MAX_BYTES = 8 * 1024 * 1024;

export interface DjProfileValue {
  djName: string;
  avatarDataUrl?: string;
  themeColor: string;
}

interface Props {
  value: DjProfileValue;
  onChange: (value: DjProfileValue) => void;
  disabled?: boolean;
  compact?: boolean;
}

export function DjProfileEditor({value, onChange, disabled, compact}: Props) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [error, setError] = useState('');
  const avatar = safeAvatarDataUrl(value.avatarDataUrl);
  const color = /^#[0-9a-f]{6}$/i.test(value.themeColor) ? value.themeColor : stableThemeColor(value.djName);

  const pickAvatar = async (file?: File) => {
    if (!file) return;
    setError('');
    try {
      const avatarDataUrl = await resizeAvatar(file);
      onChange({...value, avatarDataUrl, themeColor: color});
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      if (inputRef.current) inputRef.current.value = '';
    }
  };

  return (
    <div className={`junction-profile-editor${compact ? ' is-compact' : ''}`}>
      <div className="junction-profile-avatar" style={{backgroundColor: color}} aria-hidden="true">
        {avatar ? <img src={avatar} alt="" /> : (value.djName.trim() || 'DJ').slice(0, 2).toLocaleUpperCase()}
      </div>
      <div className="junction-profile-fields">
        <label>
          DJ名
          <input
            value={value.djName}
            onChange={(event) => onChange({
              ...value,
              djName: limitDjName(event.target.value),
              themeColor: value.themeColor || stableThemeColor(event.target.value),
            })}
            maxLength={DJ_NAME_MAX_LENGTH}
            autoComplete="nickname"
            placeholder="他のDJに表示する名前"
            disabled={disabled}
          />
        </label>
        <div className="junction-profile-actions">
          <input
            ref={inputRef}
            className="junction-visually-hidden"
            type="file"
            accept="image/png,image/jpeg,image/webp"
            disabled={disabled}
            onChange={(event) => void pickAvatar(event.target.files?.[0])}
          />
          <button type="button" className="junction-btn junction-btn-default" disabled={disabled} onClick={() => inputRef.current?.click()}>
            アイコンを選ぶ
          </button>
          {avatar && (
            <button type="button" className="junction-btn junction-btn-quiet" disabled={disabled} onClick={() => onChange({...value, avatarDataUrl: ''})}>
              削除
            </button>
          )}
        </div>
      </div>
      {error && <p className="junction-card-error" role="alert">{error}</p>}
    </div>
  );
}

export async function resizeAvatar(file: File): Promise<string> {
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) {
    throw new Error('PNG、JPEG、WebPの画像を選択してください。');
  }
  if (file.size > SOURCE_MAX_BYTES) throw new Error('8MB以下の画像を選択してください。');

  const sourceUrl = URL.createObjectURL(file);
  try {
    const image = await loadImage(sourceUrl);
    const crop = Math.min(image.naturalWidth, image.naturalHeight);
    const sx = Math.max(0, (image.naturalWidth - crop) / 2);
    const sy = Math.max(0, (image.naturalHeight - crop) / 2);
    const sizes = [128, 112, 96, 80, 72, 64];
    const qualities = [0.72, 0.58, 0.46, 0.36, 0.28];

    for (const size of sizes) {
      const canvas = document.createElement('canvas');
      canvas.width = size;
      canvas.height = size;
      const context = canvas.getContext('2d');
      if (!context) throw new Error('画像を処理できませんでした。');
      context.fillStyle = '#172330';
      context.fillRect(0, 0, size, size);
      context.drawImage(image, sx, sy, crop, crop, 0, 0, size, size);
      for (const quality of qualities) {
        const result = canvas.toDataURL('image/jpeg', quality);
        if (result.length <= AVATAR_MAX_CHARS) return result;
      }
    }
    throw new Error('アイコン画像を十分小さくできませんでした。別の画像を選択してください。');
  } finally {
    URL.revokeObjectURL(sourceUrl);
  }
}

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error('画像を読み込めませんでした。'));
    image.src = url;
  });
}
