def allow_shopify_frame(response, request):
	if request.path.startswith("/shopify_app"):
		response.headers.pop("X-Frame-Options", None)
		shop = request.args.get("shop", "")
		response.headers["Content-Security-Policy"] = (
			f"frame-ancestors https://admin.shopify.com https://{shop};"
			if shop.endswith(".myshopify.com")
			else "frame-ancestors https://admin.shopify.com;"
		)
