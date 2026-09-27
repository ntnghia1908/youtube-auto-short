# CL1.2 — mẫu 20 dòng liên tiếp (G6)

Video `qcqQbMj4s-w` (My daily routine | Chinese Vlog | HSK 2-4), track `zh-CN`, dòng s00001–s00020 (= batch 1 của cả hai model, không chọn lọc). Prompt `v1`, think off, temperature 0, seed 42, num_ctx 8192. `zh`/timestamp lấy từ phụ đề; `pinyin`/`vi` do model sinh.

| id | zh | pinyin 14b | vi 14b | pinyin 30b | vi 30b |
|---|---|---|---|---|---|
| s00001 | 我现在要出门去上班啦 | wǒ xiànzài yào chūmén qù shàngbān lā | Tôi sắp ra ngoài đi làm rồi | wǒ xiàn zài yào chū mén qù shàng bān la | Tôi đang chuẩn bị đi làm rồi |
| s00002 | 跟我一起去看看吧 | gēn wǒ yīqǐ qù kàn kàn ba | Hãy cùng tôi đi xem qua nhé | gēn wǒ yī qǐ qù kàn kàn ba | Cùng tôi đi xem thử nhé |
| s00003 | 拜拜 | bài bai | Tạm biệt | bái bái | Tạm biệt |
| s00004 | 今天路上的车特别的少 | jīntiān lùshàng de chē tèbié de shǎo | Hôm nay trên đường có rất ít xe | jīn tiān lù shàng de chē tè bié de shǎo | Hôm nay trên đường xe cộ rất ít |
| s00005 | 这样的话就能省很多时间 | hànyàng de jiù néng shěng hěn duō shíjiān | Như vậy sẽ tiết kiệm được nhiều thời gian | zhè yàng de jiù néng shěng hěn duō shí jiān | Như vậy sẽ tiết kiệm được rất nhiều thời gian |
| s00006 | 天气也不错 | tiānqì yě búcuò | Thời tiết cũng không tồi | tiān qì yě bù cuò | Thời tiết cũng rất tốt |
| s00007 | 我现在在车站等车 | wǒ xiànzài zài chēzhàn děng chē | Tôi đang ở trạm xe buýt chờ xe | wǒ xiàn zài zài chē zhàn děng chē | Bây giờ tôi đang đợi xe ở ga |
| s00008 | 这个地方有女性专用车厢 | zhège dìfāng yǒu nǚxìng zhuānyòng chēxiāng | Nơi này có toa xe dành riêng cho phụ nữ | zhè ge dì fāng yǒu nǚ xìng zhuān yòng chē xiāng | Nơi này có toa xe dành cho nữ |
| s00009 | 也有自动贩卖机可以买水 | yě yǒu zìdòng mài fàn jī kěyǐ mǎi shuǐ | Cũng có máy bán tự động để mua nước | yě yǒu zì dòng mài fā jī kě yǐ mǎi shuǐ | Cũng có máy bán hàng tự động để mua nước |
| s00010 | 旁边呢这个就是安全门 | pángbiān ne zhège jiùshì ānquán mén | Ở bên cạnh đây là cửa an toàn | páng biān ne zhè ge jiù shì ān quán mén | Bên cạnh đây là cửa an toàn |
| s00011 | 这样电车过来的时候 | zhèyàng diànchē guòlái de shíhòu | Khi xe điện đến | zhè yàng diàn chē guò lái de shí hòu | Như vậy khi tàu điện đến |
| s00012 | 就可以保障人的安全 | jiù kěyǐ bǎozhàng rén de ānquán | Sẽ đảm bảo được an toàn cho người | jiù kě yǐ bǎo zhàng rén de ān quán | sẽ đảm bảo an toàn cho người |
| s00013 | 电车过来喽 | diànchē guòlái lōu | Xe điện đến rồi | diàn chē guò lái le | Tàu điện đến rồi |
| s00014 | 我们来一起看一下 | wǒmen lái yīqǐ kàn yīxià | Chúng ta cùng xem qua nhé | wǒ men lái yī qǐ kàn yī xià | Chúng ta cùng xem một chút |
| s00015 | 电车进站了 | diànchē jìnzhàn le | Xe điện đã vào trạm | diàn chē jìn zhàn le | Tàu điện vào ga rồi |
| s00016 | 哇 | wā | Ôi | wā | Ồ |
| s00017 | 噢！看样子人不太多哦 | ō! kàn yàngzi rén bù tài duō o | À! Dường như không có nhiều người lắm | ò! kàn yàng zi rén bù tài duō o | Ồ! Có vẻ người không nhiều lắm |
| s00018 | 还有空坐 | hái yǒu kōng zuò | Còn có chỗ trống | hái yǒu kōng zuò | Vẫn còn chỗ trống |
| s00019 | 我已经到站了 | wǒ yǐjīng dào zhàn le | Tôi đã đến trạm rồi | wǒ yǐ jīng dào zhàn le | Tôi đã đến ga rồi |
| s00020 | 出口我们现在要出去了 | chūkǒu wǒmen xiànzài yào chūqù le | Chúng ta bây giờ sẽ ra ngoài | chū kǒu wǒ men xiàn zài yào chū qù le | Lối ra, chúng ta bây giờ ra ngoài |

## Nhận xét của IMPLEMENTER (không phải quyết định G6)

Lỗi thấy trong 20 dòng này:
- s00003 拜拜: 14b `bài bai` (cách đọc thường dùng), 30b `bái bái` (sai thanh).
- s00005 这样: 14b `hànyàng` (**sai âm hoàn toàn**, phải là `zhèyàng`); 30b đúng.
- s00009 贩卖机 (fànmàijī): **cả hai sai** — 14b `mài fàn jī` (đảo âm tiết), 30b `mài fā jī`.
- s00013 喽 (lou): 14b `lōu`, 30b `le` (30b đọc thành chữ khác).
- s00006 不错: 14b `búcuò` (biến điệu 不 như prompt yêu cầu), 30b `bù cuò`.
- s00002/s00014 一起/一下: cả hai viết `yīqǐ`/`yīxià` — không biến điệu 一 như prompt yêu cầu (`yìqǐ`, `yíxià`).
- Tách từ: 14b viết liền theo từ (`xiànzài`, `chūmén`); 30b trong video này tách **từng âm tiết** (`xiàn zài`, `chū mén`), trái với prompt.
- Nghĩa: cả hai dịch hiểu được, tự nhiên. s00007 车站: 14b “trạm xe buýt” (sai ngữ cảnh — đây là ga tàu điện), 30b “ga”; s00020 14b bỏ mất 出口 (“lối ra”), 30b giữ.
