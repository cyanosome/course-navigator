/* eslint-disable -- 禁止リストの検出を確かめる違反サンプル。frontend の lint の対象にしない */
import { Inter, Noto_Sans_JP } from "next/font/google";
import { Sparkles, ArrowRight } from "lucide-react";
import { motion } from "framer-motion";

const inter = Inter({ subsets: ["latin"] });
const noto = Noto_Sans_JP({ subsets: ["latin"] });

export function Hero() {
  return (
    <motion.section
      initial={{ opacity: 0, y: 24 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ ease: [0.34, 1.56, 0.64, 1] }}
      whileHover={{ scale: 1.05 }}
      style={{ boxShadow: "0 8px 24px rgba(0,0,0,0.08)", fontFamily: "'Fraunces', serif" }}
    >
      <h2 className="bg-clip-text bg-gradient-to-r from-orange-500 to-pink-500 text-transparent">
        履修の相談
      </h2>
      <Sparkles />
      <ArrowRight />
    </motion.section>
  );
}
