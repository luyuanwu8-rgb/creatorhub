import unittest

from app.platforms.wechat_article import (
    WechatArticleError,
    normalize_article_url,
    parse_article_payload,
)


class WechatArticleTests(unittest.TestCase):
    def test_normalizes_only_article_urls(self):
        url = normalize_article_url(
            "https://mp.weixin.qq.com/s/abc?foo=1#fragment"
        )
        self.assertEqual(url, "https://mp.weixin.qq.com/s/abc?foo=1")
        with self.assertRaises(WechatArticleError):
            normalize_article_url("https://example.test/article")

    def test_reads_network_metrics_and_public_read_display(self):
        metric = parse_article_payload(
            "https://mp.weixin.qq.com/s/article",
            '<meta property="og:title" content="测试文章">',
            body_text="阅读 10万+",
            extension_payload={
                "appmsgstat": {
                    "read_num": 123456,
                    "old_like_count": 273,
                    "share_count": 214,
                    "collect_count": 86,
                    "comment_count": 33,
                }
            },
        )
        self.assertEqual(metric.title, "测试文章")
        self.assertEqual(metric.read_count, 123456)
        self.assertEqual(metric.read_display, "10万+")
        self.assertEqual(metric.like_count, 273)
        self.assertEqual(metric.share_count, 214)
        self.assertEqual(metric.collect_count, 86)
        self.assertEqual(metric.comment_count, 33)
        self.assertEqual(metric.source, "public_page_network")

    def test_public_read_display_is_kept_when_network_metrics_are_absent(self):
        metric = parse_article_payload(
            "https://mp.weixin.qq.com/s/article",
            "<title>文章</title>",
            body_text="阅读 10万+",
        )
        self.assertEqual(metric.read_count, 100000)
        self.assertEqual(metric.read_display, "10万+")
        self.assertIsNone(metric.like_count)


if __name__ == "__main__":
    unittest.main()
