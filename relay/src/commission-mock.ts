YªçŠx-®éÜj×¢ëiºÚ+Š§j[h‘éÜ¢éíãÝ5N‹Z–‹­¦ëeŠw¬Õ¥µÁ½ÉÐ…ÍÍ•ÉÐ™É½´€‰¹½‘”é…ÍÍ•ÉÐ½ÍÑÉ¥Ðˆì)¥µÁ½ÉÐìÉ…¹‘½µUU%ô™É½´€‰¹½‘”éÉåÁÑ¼ˆì)¥µÁ½ÉÐìµ­‘Ñ•µÁMå¹Œ°É•…‘¥±•Må¹Œ°ÉµMå¹Œô™É½´€‰¹½‘”é™Ìˆì)¥µÁ½ÉÐìÑµÁ‘¥Èô™É½´€‰¹½‘”é½Ìˆì)¥µÁ½ÉÐì©½¥¸ô™É½´€‰¹½‘”éÁ…Ñ ˆì)¥µÁ½ÉÐìÍ•ÑQ¥µ•½ÕÐ…Ì‘•±…äô™É½´€‰¹½‘”éÑ¥µ•ÉÌ½ÁÉ½µ¥Í•Ìˆì)¥µÁ½ÉÐì±¥•¹Ðô™É½´€‰µ½“ŽôÖÚ$z{-®éÜj×omplete");
    await app.stop().catch(() => undefined);
    rmSync(temporaryRoot, { recursive: true, force: true });
  }
}

main().catch((error) => {
  process.stderr.write(
    `Mock commissioning failed: ${error instanceof Error ? error.stack : String(error)}\n`,
  );
  process.exitCode = 1;
});
