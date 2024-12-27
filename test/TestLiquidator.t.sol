// SPDX-License-Identifier: GPL-2.0-or-later

pragma solidity ^0.8.24;

import {Test, console} from "forge-std/Test.sol";
import {Liquidator} from "../contracts/Liquidator.sol";
import {IEVault, IRiskManager, IBorrowing, ILiquidation} from "../contracts/IEVault.sol";
import {IERC4626, IERC20} from "../contracts/IEVault.sol";


contract LiquidatorTest is Test {
    address constant LIQUIDATOR_CONTRACT_ADDRESS = 0x95121eb54007C4e1B41Aa5E9248000e34cbC3729;
    address constant ACCOUNT = 0xBE18F84532d8F7fB6D7919401c0096F3E257db86;
    address constant VAULT = 0x298966b32C968884F716F762f6759e8e5811aE14;
    address constant BORROW_ASSET = 0xDD629E5241CbC5919847783e6C96B2De4754e438;
    address constant COLLATERAL = 0x797DD80692c3b2dAdabCe8e30C07fDE5307D48a9;
    address constant COLLATERAL_ASSET = 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48;
    
    uint256 deployerPrivateKey = vm.envUint("LIQUIDATOR_PRIVATE_KEY");
    address liquidatorEOA = vm.addr(deployerPrivateKey);

    Liquidator liquidator;

    function setUp() public {

        liquidator = Liquidator(payable(LIQUIDATOR_CONTRACT_ADDRESS));
    }

    function testExecuteLiquidation() public {
        (uint256 repayAmount, uint256 seizedCollateralAmount) = ILiquidation(VAULT).checkLiquidation(LIQUIDATOR_CONTRACT_ADDRESS, ACCOUNT, COLLATERAL);

        Liquidator.LiquidationParams memory params = Liquidator.LiquidationParams({
            violatorAddress: ACCOUNT,
            vault: VAULT,
            borrowedAsset: BORROW_ASSET,
            collateralVault: COLLATERAL,
            collateralAsset: COLLATERAL_ASSET,
            repayAmount: repayAmount,
            seizedCollateralAmount: seizedCollateralAmount,
            receiver: liquidatorEOA
        });

        console.log("Repay amount: ", repayAmount);
        console.log("Seized collateral: ", seizedCollateralAmount);
        console.log("Collateral as assets: ", IERC4626(COLLATERAL).convertToAssets(seizedCollateralAmount));   
    }

    function testLiquidatorWithPythUpdate() public {
        bytes[] memory pythUpdateData = new bytes[](1);
        pythUpdateData[0] = hex"504e41550100000003b801000000040d00430b259b8339a0ce13437f029b730172832c61413ffb0423a1d775b6a3ed7cc959e91999253cd6ddeee89762692fc8514a8b694dd94a3321013820c7e3d012670002083c46ff3abf42f65b641554b7a61e5f882c27dd321f47239c6fe779be3ba68c31c67e255425fe0f77fb8b55fa81b46956b14ba493f6f39339335196757dadc40103cdc59afee22cd50f9889a8c6d614e4ce971dfff1865e5ea697417f6c2071df3a39f9ab58e7996cc10f95dd68c9b0eff64f264cd2e621ef0ce9d879aa6c46e24001044ffad84e81d8fd8fa70706ad8217c88c18ef9219a5b171f193bf23a577b395460e506456048c70fad2d12b2718141eb91efe0efcb0ef02932a9576ef7375507a010603b2781fbc65a9476e656cc95af4a3046e82f97c3ffe80d998bbed068c0c0a3d43bac0d6cbcfb44a5aaec842536c69b2cae69b9d6400edf497558e0bf838e7ad0008f58f6f4382b3e299d275d2864b7ab2fe282281d3d4587b3a2229fabf05997549681ca791ea1289a5fd8783868960c269d3a6346b39775d1ada91cadf130c939b000aabae762ea9f7974936a314d291643538454bb29077a940f95a4d0bb650a7dcb76c3fd96385591131013103cc0cb1b8646a31ec8a1ae46db0e96d9bcac696a121000c19237de2f6422cad69ee0292d7c0f435e42607fbcf581db28f2f7c2a57439dd30178ef9af907643dc5f23496dec77eadad3c1903b2da6f008ad1589eacf388f0010de7ebf559918d7bbd82ec20469cfb6e74b89013ba8f3bd549dc5c08e5f1b68d334cd4544da7dd5fc716aefdf53c494de9aa1eb3cd350f931406bc2f237fc8c11c010ec4111361969a29ce40a78a2261454fe8565e1ba3341009d4c186e13f9d749809657cceb6dcf802818c397f3e6a4e1530556ff9b3448d62720d9b9eb2cdc7f3be010febce9984e3d65aff66b8119bc56715a2a077def83f80b1fbd8289113feb89e3873c7839951ecb3512a92864222f0a720f6c2b0d6ec7c721d8efed70342a6fbaa00109e3bda4c1b85188ae93f73e47d17900ece6a2a4112bafe780b150cdaea72e5bc79caded35061933d20e9021f4c5e85875352d8df2403359476531089aebd6f060112fc281d4e21f3ebb87afd6d287df00c003e203864d61310f7eefec85641ae69f030d3c531185ec4f298719803cd77f21ba514384e0d90da866f603c8883dc45c90066eaa75400000000001ae101faedac5851e32b9b23b5f9411a8c2bac4aae3ed4dd7b811dd1a72ea4aa710000000004d69e860141555756000000000009e223b7000027103d7fb8d6236feea98baed2249f8fdef4c6f9e54b03005500ca3ba9a619a4b3755c10ac7d5e760275aa95e9823d38a84fedd416856cdba37c00000000068997fd000000000007c17ffffffff80000000066eaa7540000000066eaa754000000000689a9d8000000000005d6e20adf469931287004c1a28479fdc444ba2c753fd68852e371410edd9d43c71dbae11408cdf5bb62c0b241ef91dff02756a32140d8911f79c3e5381816c62342a9521b993d60213ed22ffa6e6c51d48089e8599d63d61822c6022b9985b08c6ab16d3e9d516ae4763f50d171273f73e4b82f843036f8edc0959de902cb4040d3a443a392e05b209fa587c949052bab36f97645427f48d2007f01626e1568e46f022e475ccb534b57ae5ad2e2088538fef5c5a46045be547c6d2a28b1a32f2eeea61de902d151f0fb11ee0055006ec879b1e9963de5ee97e9c8710b742d6228252a5e2ca12d4ae81d7fe5ee8c5d0000000005f44b850000000000021abffffffff80000000066eaa7540000000066eaa7540000000005f4550a0000000000020e150a626ade5a18d656ebfa72b93469413d7df85d2c6ac0b7f1b0b1bb433ca37a943baf94e3cb44cab57e406883444fef27da7caa392bdbdcc8f8ab9b59c0ea8159957eab38bcd0989c9476aefaeee7ec1caceeeb96b97e9aee5d0f5cbf218577094aca5c18d110f636c028beba38ddf8c1f81fb6b90148bdaac5f1be3cefbfbeb2f436f426bef95eedffc8e3ca55e9b46f5744f1856250e8d4f1ae13b8f4259fe1741f7b04f34b6915613be866411873e091287dc7b3547c6d2a28b1a32f2eeea61de902d151f0fb11ee005500e393449f6aff8a4b6d3e1165a7c9ebec103685f3b41e60db4277b5b6d10e732600000000064b1420000000000007f0cafffffff80000000066eaa7540000000066eaa75400000000064b1a3f000000000007ce760a1f1a8f3094cdc0357e16e9209615823efeae4141923f98878c0264198f28da4e4a5a24886b746c0293e2d2f6f806e47781526271de6de2b15215daaa9b7e9fc2be6896d1efcb5fa0d685c400c6d276403ea9cc126dc6240cb3de7c34d1a400daa2b2584333ef6a33a1085272c18dc7bd1d83877e5ee7a4ff3e9b7a3ca8d0ac7436e0d4ef07b615285ecfc5c7ab36f97645427f48d2007f01626e1568e46f022e475ccb534b57ae5ad2e2088538fef5c5a46045be547c6d2a28b1a32f2eeea61de902d151f0fb11ee";
        uint256 updateFee = 3;
        (uint256 collateral, uint256 liability) = liquidator.simulatePythUpdateAndGetAccountStatus{value: updateFee}(pythUpdateData, updateFee, VAULT, ACCOUNT);

        console.log(collateral, liability);
    }
}
