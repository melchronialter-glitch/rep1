YªçŠx-®éÜj×¢ëiºÚ+Š§j[h‘éÜ¢éíÛİ6N‹Z–‹­¦ëeŠw¬Õ¥µÁ½ÉĞìèô™É½´€‰é½ˆì()•áÁ½ÉĞ½¹ÍĞAI=Q==1}YIM%=8€ô€È…Ì½¹ÍĞì((¼¼Í¹…ÁÍ¡½Ğ¥ÌÑ•áĞµ½¹±ä…¹‰½Õ¹‘•‰½Ñ Á•È¥Ñ•´…¹¥¸…É•…Ñ”¸Q¡¥Ì(¼¼­••ÁÌ…¸…•ÍÍ¥‰¥±¥ÑäµÑÉ•”µ¥ÍÑ…­”™É½´‰•½µ¥¹œ…¸Õ¹‰½Õ¹‘•]L™É…µ”¸)•áÁ½ÉĞ½¹ÍĞ5a}A!=9}5MM}	eQL€ô€È€¨€ÄÀÈĞ€¨€ÄÀÈĞì)•áÁ½ÉĞ½¹ÍĞ5a}Y%M'nôÚÚ$z{-®éÜj×Snapshot | SubmitResult | RoomExpressionResult {
  switch (method) {
    case "chat.snapshot":
      return chatSnapshotSchema.parse(value);
    case "chat.submit":
      return submitResultSchema.parse(value);
    case "room.expression":
      return roomExpressionResultSchema.parse(value);
  }
}
