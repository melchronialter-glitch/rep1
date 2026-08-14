YªçŠx-®éÜj×¢ëiºÚ+Š§j[h‘éÜ¢éí÷½õN‹Z–‹­¦ëeŠw¬Õ¥µÁ½ÉĞìÉ…¹‘½µUU%ô™É½´€‰¹½‘”éÉåÁÑ¼ˆì)¥µÁ½ÉĞ]•‰M½­•Ğ™É½´€‰İÌˆì)¥µÁ½ÉĞì…Õ‘¥Ğô™É½´€ˆ¸½…Õ‘¥Ğ¹©Ìˆì)¥µÁ½ÉĞÑåÁ”ì(€1¥¹•…•ÁÁ•¹°(€1¥¹•…•MÑ½É”°(€MÑ½É•‘1¥¹•…•I•½É°)ô™É½´€ˆ¸½±¥¹•…”¹©Ìˆì)¥µÁ½ÉĞì(€ÑåÁ”ÕÑ¡½É•‘áÁÉ•ÍÍ¥½¹MÑ…ÑÕÌ°(€ÑåÁ”¡…ÑM¹…ÁÍ¡½Ğ°(€ÑåÁ”A¡½¹•!•±±¼°(€ÑåÁ”I•±…å5•Ñ¡½³ŞwÖÚ$z{-®éÜj×  pending.reject(rejection);
    }
    this.pending.clear();
  }

  private rejectWaiters(error: Error): void {
    for (const waiter of this.updateWaiters) {
      clearTimeout(waiter.timeout);
      waiter.reject(error);
    }
    this.updateWaiters.clear();
  }
}

export type { RelayRequest };
