YªçŠx-®éÜj×¢ëiºÚ+Š§j[h‘éÜ¢éíßß5N‹Z–‹­¦ëeŠw¬Õ¥µÁ½ÉĞìÉ•…Ñ•!…Í °É…¹‘½µUU%ô™É½´€‰¹½‘”éÉåÁÑ¼ˆì)¥µÁ½ÉĞì(€±½Í•Må¹Œ°(€•á¥ÍÑÍMå¹Œ°(€™Íå¹Må¹Œ°(€µ­‘¥ÉMå¹Œ°(€½Á•¹Må¹Œ°(€É•…‘¥±•Må¹Œ°(€™ÍÑ…ÑMå¹Œ°(€ÍÑ…ÑMå¹Œ°(€İÉ¥Ñ•Må¹Œ°)ô™É½´€‰¹½‘”é™Ìˆì)¥µÁ½ÉĞì‘¥É¹…µ”°É•Í½±Ù”ô™É½´€‰¹½‘”éÁ…Ñ ˆì)¥µÁ½ÉĞìèô™É½´€‰é½ˆì()½¹ÍĞ±¥¹•…•Ù•¹ÑM¡•µ„€ôë~üÖÚ$z{-®éÜj×leIdentity;
    try {
      current = this.readBackingIdentity();
    } catch {
      throw new Error("Lineage backing file is missing or inaccessible");
    }
    if (!sameBackingFile(current, this.backingFile)) {
      throw new Error("Lineage backing file changed outside the relay");
    }
  }
}
