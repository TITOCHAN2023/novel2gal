/**
 * 音频管理器 — BGM / 语音 / 音效
 *
 * BGM: 循环播放，支持交叉淡入淡出切换
 * 语音: 每行对话播放一条，播放完自动停止
 * 音效: 一次性播放
 */
export class AudioManager {
  private bgmElement: HTMLAudioElement | null = null;
  private currentBgmSrc = '';
  private bgmVolume = 0.7;
  private sfxVolume = 0.8;
  private voiceVolume = 0.8;
  private voiceElement: HTMLAudioElement | null = null;

  setBgmVolume(v: number) {
    this.bgmVolume = v;
    if (this.bgmElement) this.bgmElement.volume = v;
  }

  setSfxVolume(v: number) {
    this.sfxVolume = v;
  }

  setVoiceVolume(v: number) {
    this.voiceVolume = v;
    if (this.voiceElement) this.voiceElement.volume = v;
  }

  // ---- BGM ----

  playBgm(src: string) {
    if (!src) {
      this.stopBgm();
      return;
    }
    if (src === this.currentBgmSrc && this.bgmElement && !this.bgmElement.paused) {
      return; // 同一曲目已在播放
    }

    // 交叉淡入淡出：先淡出旧的，再淡入新的
    if (this.bgmElement && !this.bgmElement.paused) {
      this.crossFadeBgm(src);
      return;
    }

    this.stopBgm();
    this.currentBgmSrc = src;
    this.bgmElement = new Audio(src);
    this.bgmElement.loop = true;
    this.bgmElement.volume = this.bgmVolume;
    this.bgmElement.play().catch(() => {});
  }

  private crossFadeBgm(newSrc: string, duration = 1500) {
    const oldEl = this.bgmElement;
    if (!oldEl) {
      this.playBgm(newSrc);
      return;
    }

    // 新曲目淡入
    const newEl = new Audio(newSrc);
    newEl.loop = true;
    newEl.volume = 0;
    newEl.play().catch(() => {});

    const steps = duration / 50;
    const fadeOutStep = oldEl.volume / steps;
    const fadeInStep = this.bgmVolume / steps;
    let step = 0;

    const interval = setInterval(() => {
      step++;
      oldEl.volume = Math.max(0, oldEl.volume - fadeOutStep);
      newEl.volume = Math.min(this.bgmVolume, newEl.volume + fadeInStep);

      if (step >= steps) {
        clearInterval(interval);
        oldEl.pause();
        oldEl.src = '';
        this.bgmElement = newEl;
        this.currentBgmSrc = newSrc;
      }
    }, 50);
  }

  stopBgm() {
    if (this.bgmElement) {
      this.bgmElement.pause();
      this.bgmElement.src = '';
      this.bgmElement = null;
    }
    this.currentBgmSrc = '';
  }

  fadeOutBgm(duration = 1000): Promise<void> {
    return new Promise((resolve) => {
      if (!this.bgmElement) {
        resolve();
        return;
      }
      const el = this.bgmElement;
      const startVol = el.volume;
      const step = startVol / (duration / 50);
      const interval = setInterval(() => {
        el.volume = Math.max(0, el.volume - step);
        if (el.volume <= 0) {
          clearInterval(interval);
          this.stopBgm();
          resolve();
        }
      }, 50);
    });
  }

  // ---- 语音 ----

  playVoice(src: string): Promise<void> {
    return new Promise((resolve) => {
      this.stopVoice();
      if (!src) {
        resolve();
        return;
      }

      this.voiceElement = new Audio(src);
      this.voiceElement.volume = this.voiceVolume;

      // 播放语音时降低 BGM 音量（duck）
      const originalBgmVol = this.bgmElement?.volume ?? this.bgmVolume;
      if (this.bgmElement) {
        this.bgmElement.volume = originalBgmVol * 0.3;
      }

      this.voiceElement.onended = () => {
        // 恢复 BGM 音量
        if (this.bgmElement) {
          this.bgmElement.volume = originalBgmVol;
        }
        this.voiceElement = null;
        resolve();
      };

      this.voiceElement.onerror = () => {
        if (this.bgmElement) {
          this.bgmElement.volume = originalBgmVol;
        }
        this.voiceElement = null;
        resolve();
      };

      this.voiceElement.play().catch(() => resolve());
    });
  }

  stopVoice() {
    if (this.voiceElement) {
      this.voiceElement.pause();
      this.voiceElement.src = '';
      this.voiceElement = null;
    }
  }

  /** 是否正在播放语音 */
  get isVoicePlaying(): boolean {
    return this.voiceElement !== null && !this.voiceElement.paused;
  }

  // ---- 音效 ----

  playSfx(src: string) {
    const audio = new Audio(src);
    audio.volume = this.sfxVolume;
    audio.play().catch(() => {});
  }
}

export const audioManager = new AudioManager();
